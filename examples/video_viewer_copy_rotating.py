# Copyright (c) Meta Platforms, Inc. and its affiliates.
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import ctypes
import math
import os
import random
import string
import sys
import time
from collections import deque
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

flags = sys.getdlopenflags()
sys.setdlopenflags(flags | ctypes.RTLD_GLOBAL)

import magnum as mn
import numpy as np
from habitat.articulated_agent_controllers import (
    HumanoidRearrangeController,
    SeqPoseController,
)
from habitat.articulated_agents.humanoids.kinematic_humanoid import KinematicHumanoid
from habitat.datasets.rearrange.navmesh_utils import get_largest_island_index
from magnum import shaders, text
from magnum.platform.glfw import Application

import habitat_sim
from habitat_sim import ReplayRenderer, ReplayRendererConfiguration, physics
from habitat_sim.logging import LoggingContext, logger
from habitat_sim.utils.common import quat_from_angle_axis
from habitat_sim.utils.settings import default_sim_settings, make_cfg


def file_endswith(filepath: str, end_str: str) -> bool:
    """
    Return whether or not the file ends with a string.
    """
    return filepath.endswith(end_str)


def find_files(
    root_dir: str, discriminator: Callable[[str, str], bool], disc_str: str
) -> List[str]:
    """
    Recursively find all filepaths under a root directory satisfying a particular constraint as defined by a discriminator function.

    :param root_dir: The roor directory for the recursive search.
    :param discriminator: The discriminator function which takes a filepath and discriminator string and returns a bool.

    :return: The list of all absolute filepaths found satisfying the discriminator.
    """
    filepaths: List[str] = []

    if not os.path.exists(root_dir):
        print(" Directory does not exist: " + str(dir))
        return filepaths

    for entry in os.listdir(root_dir):
        entry_path = os.path.join(root_dir, entry)
        if os.path.isdir(entry_path):
            sub_dir_filepaths = find_files(entry_path, discriminator, disc_str)
            filepaths.extend(sub_dir_filepaths)
        # apply a user-provided discriminator function to cull filepaths
        elif discriminator(entry_path, disc_str):
            filepaths.append(entry_path)
    return filepaths


class ContinuousPathFollower:
    def __init__(self, sim, path, agent_scene_node, waypoint_threshold):
        self._sim = sim
        self._points = path.points[:]
        assert len(self._points) > 0
        self._length = path.geodesic_distance
        self._node = agent_scene_node
        self._threshold = waypoint_threshold
        self._step_size = 0.01
        self.progress = 0  # geodesic distance -> [0,1]
        self.waypoint = path.points[0]

        # setup progress waypoints
        _point_progress = [0]
        _segment_tangents = []
        _length = self._length
        for ix, point in enumerate(self._points):
            if ix > 0:
                segment = point - self._points[ix - 1]
                segment_length = np.linalg.norm(segment)
                segment_tangent = segment / segment_length
                _point_progress.append(
                    segment_length / _length + _point_progress[ix - 1]
                )
                # t-1 -> t
                _segment_tangents.append(segment_tangent)
        self._point_progress = _point_progress
        self._segment_tangents = _segment_tangents
        # final tangent is duplicated
        self._segment_tangents.append(self._segment_tangents[-1])

        print("self._length = " + str(self._length))
        print("num points = " + str(len(self._points)))
        print("self._point_progress = " + str(self._point_progress))
        print("self._segment_tangents = " + str(self._segment_tangents))

    def pos_at(self, progress):
        if progress <= 0:
            return self._points[0]
        elif progress >= 1.0:
            return self._points[-1]

        path_ix = 0
        for ix, prog in enumerate(self._point_progress):
            if prog > progress:
                path_ix = ix
                break

        segment_distance = self._length * (progress - self._point_progress[path_ix - 1])
        return (
            self._points[path_ix - 1]
            + self._segment_tangents[path_ix - 1] * segment_distance
        )

    def update_waypoint(self):
        if self.progress < 1.0:
            wp_disp = self.waypoint - self._node.absolute_translation
            wp_dist = np.linalg.norm(wp_disp)
            node_pos = self._node.absolute_translation
            step_size = self._step_size
            threshold = self._threshold
            while wp_dist < threshold:
                self.progress += step_size
                self.waypoint = self.pos_at(self.progress)
                if self.progress >= 1.0:
                    self.waypoint = self.pos_at(self.progress) + self._segment_tangents[
                        -1
                    ] / np.linalg.norm(self._segment_tangents[-1])
                    break
                wp_disp = self.waypoint - node_pos
                wp_dist = np.linalg.norm(wp_disp)


class FollowCam:
    """
    Camera which follows a humanoid smoothly.
    """

    def __init__(self, sim) -> None:
        self.sim = sim
        self.humanoid = None
        self.cur_pos = mn.Vector3()
        self.cur_orient = mn.Quaternion()
        self.target_pos = mn.Vector3()
        self.target_orient = mn.Quaternion()
        self.collision_free_look = True
        self.pos_q = deque()
        self.path_follower = None
        self.path_follow = False
        # option to rotate the local camera point over time
        self.local_y_rot = 0
        self.local_y_rot_inc = math.pi / 4.0

    def set_humanoid(self, humanoid):
        self.humanoid = humanoid
        if self.path_follower is not None:
            self.path_follower._node = self.humanoid.sim_obj.root_scene_node

    def set_path(self, path):
        self.path_follower = ContinuousPathFollower(
            self.sim,
            path,
            self.humanoid.sim_obj.root_scene_node,
            waypoint_threshold=2.4,
        )
        self.path_follower.update_waypoint()

    def update_state(self):
        """
        Update the state of the camera from the target.
        """
        self.local_y_rot = self.sim.get_world_time() * self.local_y_rot_inc
        self.local_y_rot_quat = mn.Quaternion.rotation(
            mn.Rad(self.local_y_rot), mn.Vector3(0, 1, 0)
        )

        # self.target_pos = self.humanoid.base_pos + mn.Vector3(1.0, 2.0, 0.55)
        self.target_pos = (
            self.humanoid.base_pos
            + self.local_y_rot_quat.transform_vector(mn.Vector3(1.0, 2.0, 0.55))
        )
        # Initial camera angle (v2)
        # local_point = mn.Vector3(1.0, 1.0, -0.55)
        # local_point = self.local_y_rot_quat.transform_vector(local_point)
        # print(local_point)
        # self.target_pos = self.humanoid.sim_obj.transformation.transform_point(
        #     local_point
        # )
        # Front facing camera angle (v3)
        # self.target_pos = self.humanoid.sim_obj.transformation.transform_point(
        #    mn.Vector3(0, 0.0, 1.5)
        # )

        if self.path_follow and self.path_follower is not None:
            self.path_follower.update_waypoint()
            self.target_pos = self.path_follower.waypoint + mn.Vector3(0, 1.5, 0)

        self.pos_q.appendleft(self.target_pos)
        if len(self.pos_q) > 20:
            self.pos_q.pop()
        frame_target = mn.Vector3()
        for item in self.pos_q:
            frame_target += item
        frame_target /= len(self.pos_q)

        look_target = self.humanoid.base_pos + mn.Vector3(0, 1.3, 0)
        frame_target = self.target_pos

        if self.collision_free_look:
            inv_look_vec = frame_target - look_target
            max_dist = inv_look_vec.length()
            inv_look_dir = inv_look_vec / max_dist
            raycast_results = self.sim.cast_ray(
                habitat_sim.geo.Ray(look_target, inv_look_dir)
            )

            ao_obj_ids = list(self.humanoid.sim_obj.link_object_ids.keys())

            for hit in raycast_results.hits:
                if hit.object_id not in ao_obj_ids:
                    if hit.ray_distance < max_dist:
                        frame_target = look_target + inv_look_dir * (
                            hit.ray_distance - 0.1
                        )
                    break

        self.cur_pos = self.cur_pos + (frame_target - self.cur_pos) * 0.1

        self.target_orient = mn.Quaternion.from_matrix(
            mn.Matrix4.look_at(
                eye=self.cur_pos,
                target=look_target,
                up=mn.Vector3(0, 1.0, 0),
            ).rotation()
        )

        self.cur_orient = self.target_orient


class HabitatSimInteractiveViewer(Application):
    # the maximum number of chars displayable in the app window
    # using the magnum text module. These chars are used to
    # display the CPU/GPU usage data
    MAX_DISPLAY_TEXT_CHARS = 256

    # how much to displace window text relative to the center of the
    # app window (e.g if you want the display text in the top left of
    # the app window, you will displace the text
    # window width * -TEXT_DELTA_FROM_CENTER in the x axis and
    # window height * TEXT_DELTA_FROM_CENTER in the y axis, as the text
    # position defaults to the middle of the app window)
    TEXT_DELTA_FROM_CENTER = 0.49

    # font size of the magnum in-window display text that displays
    # CPU and GPU usage info
    DISPLAY_FONT_SIZE = 16.0

    def __init__(self, sim_settings: Dict[str, Any]) -> None:
        self.sim_settings: Dict[str:Any] = sim_settings

        self.enable_batch_renderer: bool = self.sim_settings["enable_batch_renderer"]
        self.num_env: int = (
            self.sim_settings["num_environments"] if self.enable_batch_renderer else 1
        )

        # Compute environment camera resolution based on the number of environments to render in the window.
        window_size: mn.Vector2 = (
            self.sim_settings["window_width"],
            self.sim_settings["window_height"],
        )

        configuration = self.Configuration()
        configuration.title = "Habitat Sim Interactive Viewer"
        configuration.size = window_size
        Application.__init__(self, configuration)
        self.fps: float = 30.0

        # Compute environment camera resolution based on the number of environments to render in the window.
        grid_size: mn.Vector2i = ReplayRenderer.environment_grid_size(self.num_env)
        camera_resolution: mn.Vector2 = mn.Vector2(self.framebuffer_size) / mn.Vector2(
            grid_size
        )
        self.sim_settings["width"] = camera_resolution[0]
        self.sim_settings["height"] = camera_resolution[1]

        # draw Bullet debug line visualizations (e.g. collision meshes)
        self.debug_bullet_draw = False
        # draw active contact point debug line visualizations
        self.contact_debug_draw = False
        # cache most recently loaded URDF file for quick-reload
        self.cached_urdf = ""

        # set up our movement map
        key = Application.KeyEvent.Key
        self.pressed = {
            key.UP: False,
            key.DOWN: False,
            key.LEFT: False,
            key.RIGHT: False,
            key.A: False,
            key.D: False,
            key.S: False,
            key.W: False,
            key.X: False,
            key.Z: False,
        }

        # set up our movement key bindings map
        key = Application.KeyEvent.Key
        self.key_to_action = {
            key.UP: "look_up",
            key.DOWN: "look_down",
            key.LEFT: "turn_left",
            key.RIGHT: "turn_right",
            key.A: "move_left",
            key.D: "move_right",
            key.S: "move_backward",
            key.W: "move_forward",
            key.X: "move_down",
            key.Z: "move_up",
        }

        # Load a TrueTypeFont plugin and open the font file
        self.display_font = text.FontManager().load_and_instantiate("TrueTypeFont")
        relative_path_to_font = "../data/fonts/ProggyClean.ttf"
        self.display_font.open_file(
            os.path.join(os.path.dirname(__file__), relative_path_to_font),
            13,
        )

        # Glyphs we need to render everything
        self.glyph_cache = text.GlyphCache(mn.Vector2i(256))
        self.display_font.fill_glyph_cache(
            self.glyph_cache,
            string.ascii_lowercase
            + string.ascii_uppercase
            + string.digits
            + ":-_+,.! %µ",
        )

        # magnum text object that displays CPU/GPU usage data in the app window
        self.window_text = text.Renderer2D(
            self.display_font,
            self.glyph_cache,
            HabitatSimInteractiveViewer.DISPLAY_FONT_SIZE,
            text.Alignment.TOP_LEFT,
        )
        self.window_text.reserve(HabitatSimInteractiveViewer.MAX_DISPLAY_TEXT_CHARS)

        # text object transform in window space is Projection matrix times Translation Matrix
        # put text in top left of window
        self.window_text_transform = mn.Matrix3.projection(
            self.framebuffer_size
        ) @ mn.Matrix3.translation(
            mn.Vector2(self.framebuffer_size)
            * mn.Vector2(
                -HabitatSimInteractiveViewer.TEXT_DELTA_FROM_CENTER,
                HabitatSimInteractiveViewer.TEXT_DELTA_FROM_CENTER,
            )
        )
        self.shader = shaders.VectorGL2D()

        # make magnum text background transparent
        mn.gl.Renderer.enable(mn.gl.Renderer.Feature.BLENDING)
        mn.gl.Renderer.set_blend_function(
            mn.gl.Renderer.BlendFunction.ONE,
            mn.gl.Renderer.BlendFunction.ONE_MINUS_SOURCE_ALPHA,
        )
        mn.gl.Renderer.set_blend_equation(
            mn.gl.Renderer.BlendEquation.ADD, mn.gl.Renderer.BlendEquation.ADD
        )

        # variables that track app data and CPU/GPU usage
        self.num_frames_to_track = 60

        # Cycle mouse utilities
        self.mouse_interaction = MouseMode.LOOK
        self.mouse_grabber: Optional[MouseGrabber] = None
        self.previous_mouse_point = None

        # toggle physics simulation on/off
        self.simulating = True

        # toggle a single simulation step at the next opportunity if not
        # simulating continuously.
        self.simulate_single_step = False

        # configure our simulator
        self.cfg: Optional[habitat_sim.simulator.Configuration] = None
        self.sim: Optional[habitat_sim.simulator.Simulator] = None
        self.tiled_sims: list[habitat_sim.simulator.Simulator] = None
        self.replay_renderer_cfg: Optional[ReplayRendererConfiguration] = None
        self.replay_renderer: Optional[ReplayRenderer] = None
        self.reconfigure_sim()

        # compute NavMesh if not already loaded by the scene.
        if (
            not self.sim.pathfinder.is_loaded
            and self.cfg.sim_cfg.scene_id.lower() != "none"
        ):
            self.navmesh_config_and_recompute()

        self.largest_indoor_island = get_largest_island_index(
            self.sim.pathfinder, self.sim, allow_outdoor=False
        )

        # humanoid control
        self.humanoid = None
        self.humanoid_controller = None
        self.humanoid_cur_path = None
        self.humanoid_cur_waypoint = 0
        self.humanoid_models = self.get_humanoid_models("data/humanoids/humanoid_data/")
        self.humanoid_cur_model_index = 1
        self.humanoid_seq_motions = find_files(
            "data/humanoids/humanoid_data/mdm_data/", file_endswith, ".pkl"
        )
        self.prev_humanoid_base_state = (
            None  # provides consistency between loading of new model
        )
        # self.init_humanoid(random.choice(self.humanoid_models))
        self.follow_cam = FollowCam(self.sim)
        self.init_humanoid(self.humanoid_models[self.humanoid_cur_model_index])
        self.follow_cam.cur_pos = self.humanoid.base_pos + mn.Vector3(1.0, 2.0, 0.55)
        self.obs_buffer = []
        self.humanoid_model_inc_freq = 2.5
        self.humanoid_model_last_inc = 0

        self.time_since_last_simulation = 0.0
        LoggingContext.reinitialize_from_env()
        logger.setLevel("INFO")
        self.print_help_text()

    def get_humanoid_models(self, filepath: str) -> List[Tuple[str, str]]:
        """
        Get a list of humanoid urdfs and accompanying motion files from a directory.
        Assumes naming format between model and motion files: ("female_0.urdf" -> "female_0_motion_data_smplx.pkl")
        """
        models = []
        urdfs = find_files(filepath, file_endswith, ".urdf")
        for urdf in urdfs:
            model_name = urdf.split(".urdf")[0]
            motion_path = model_name + "_motion_data_smplx.pkl"
            if os.path.isfile(motion_path):
                models.append((urdf, motion_path))
        return models

    def humanoid_new_path(self):
        """
        Does path planning for the humanoid.
        """
        path = habitat_sim.ShortestPath()
        path.requested_start = self.humanoid.base_pos
        path.requested_end = self.sim.pathfinder.get_random_navigable_point(
            island_index=self.largest_indoor_island
        )
        while not self.sim.pathfinder.find_path(path):
            continue
        self.humanoid_cur_path = path.points
        if self.follow_cam is not None:
            self.follow_cam.set_path(path)

    def update_humanoid_path_waypoint(self):
        """
        Handles choosing the next linear waypoint to pursue.
        """
        if self.humanoid_cur_path is None:
            self.humanoid_new_path()
            self.humanoid_cur_waypoint = 1
        dist_to_waypoint = np.linalg.norm(
            self.humanoid_cur_path[self.humanoid_cur_waypoint] - self.humanoid.base_pos
        )
        # print(dist_to_waypoint)
        if dist_to_waypoint < 0.1:
            self.humanoid_cur_waypoint += 1
            if self.humanoid_cur_waypoint >= len(self.humanoid_cur_path):
                self.humanoid_new_path()
                self.humanoid_cur_waypoint = 1

    def init_humanoid(
        self, model: Tuple[str, str], controller=HumanoidRearrangeController
    ):
        """
        Initialize the humanoid and controller from a model.
        """
        if self.humanoid is not None:
            self.prev_humanoid_base_state = (
                self.humanoid.base_pos,
                self.humanoid.base_rot,
                self.humanoid_controller.prev_orientation,
                self.humanoid_controller.walk_mocap_frame,
            )
            self.sim.get_articulated_object_manager().remove_object_by_handle(
                self.humanoid.sim_obj.handle
            )
        # self.humanoid_cur_path = None
        self.humanoid = KinematicHumanoid(urdf_path=model[0], sim=self.sim)
        self.humanoid.reconfigure()
        self.follow_cam.set_humanoid(self.humanoid)
        if self.prev_humanoid_base_state is None:
            self.humanoid.base_pos = self.sim.pathfinder.get_random_navigable_point(
                island_index=self.largest_indoor_island
            )
        else:
            self.humanoid.base_pos = self.prev_humanoid_base_state[0]
            self.humanoid.base_rot = float(self.prev_humanoid_base_state[1])
        self.humanoid_controller = controller(walk_pose_path=model[1])
        self.humanoid_controller.reset(self.humanoid.base_transformation)

        if self.prev_humanoid_base_state is not None:
            self.humanoid_controller.prev_orientation = self.prev_humanoid_base_state[2]
            self.humanoid_controller.walk_mocap_frame = self.prev_humanoid_base_state[3]

    def update_humanoid(self):
        """
        Called every step to update the humanoid's state from the path waypoints.
        """
        if type(self.humanoid_controller) == HumanoidRearrangeController:
            self.update_humanoid_path_waypoint()
            relative_pos = (
                self.humanoid_cur_path[self.humanoid_cur_waypoint]
                - self.humanoid.base_pos
            )
            relative_pos = relative_pos / np.linalg.norm(relative_pos) * (1.0 / 20.0)
            self.humanoid_controller.calculate_walk_pose(mn.Vector3(relative_pos))
        elif type(self.humanoid_controller) == SeqPoseController:
            self.humanoid_controller.get_pose_mdm()

        self.humanoid.set_joint_transform(
            joint_list=self.humanoid_controller.joint_pose,
            offset_transform=self.humanoid_controller.obj_transform_offset,
            base_transform=self.humanoid_controller.obj_transform_base,
        )
        bp = self.humanoid.base_pos
        bp[1] = self.sim.pathfinder.snap_point(
            bp, island_index=self.largest_indoor_island
        )[1]
        self.humanoid.base_pos = bp

    def inc_humanoid(self):
        """
        Increment the humanoid model for the scene.
        """
        self.humanoid_cur_model_index = (self.humanoid_cur_model_index + 1) % len(
            self.humanoid_models
        )
        model = self.humanoid_models[self.humanoid_cur_model_index]
        self.init_humanoid(model, controller=HumanoidRearrangeController)

    def draw_contact_debug(self):
        """
        This method is called to render a debug line overlay displaying active contact points and normals.
        Yellow lines show the contact distance along the normal and red lines show the contact normal at a fixed length.
        """
        yellow = mn.Color4.yellow()
        red = mn.Color4.red()
        cps = self.sim.get_physics_contact_points()
        self.sim.get_debug_line_render().set_line_width(1.5)
        camera_position = self.render_camera.render_camera.node.absolute_translation
        # only showing active contacts
        active_contacts = (x for x in cps if x.is_active)
        for cp in active_contacts:
            # red shows the contact distance
            self.sim.get_debug_line_render().draw_transformed_line(
                cp.position_on_b_in_ws,
                cp.position_on_b_in_ws
                + cp.contact_normal_on_b_in_ws * -cp.contact_distance,
                red,
            )
            # yellow shows the contact normal at a fixed length for visualization
            self.sim.get_debug_line_render().draw_transformed_line(
                cp.position_on_b_in_ws,
                # + cp.contact_normal_on_b_in_ws * cp.contact_distance,
                cp.position_on_b_in_ws + cp.contact_normal_on_b_in_ws * 0.1,
                yellow,
            )
            self.sim.get_debug_line_render().draw_circle(
                translation=cp.position_on_b_in_ws,
                radius=0.005,
                color=yellow,
                normal=camera_position - cp.position_on_b_in_ws,
            )

    def debug_draw(self):
        """
        Additional draw commands to be called during draw_event.
        """
        if self.debug_bullet_draw:
            render_cam = self.render_camera.render_camera
            proj_mat = render_cam.projection_matrix.__matmul__(render_cam.camera_matrix)
            self.sim.physics_debug_draw(proj_mat)
        if self.contact_debug_draw:
            self.draw_contact_debug()
        if self.humanoid_cur_path is not None:
            dblr = self.sim.get_debug_line_render()
            for pix, point in enumerate(self.humanoid_cur_path):
                if pix > 0:
                    dblr.draw_transformed_line(
                        self.humanoid_cur_path[pix - 1], point, mn.Color4.red()
                    )
        # line_points = []
        # for a in range(360):
        #     rad = (a/360.0)*math.pi*2
        #     local_point = mn.Vector3(1.0, 1.0, -0.55)
        #     local_point = mn.Quaternion.rotation(mn.Rad(rad), mn.Vector3(0,1,0)).transform_vector(local_point)
        #     line_points.append(self.humanoid.sim_obj.transformation.transform_point(local_point))
        # dblr = self.sim.get_debug_line_render()
        # for pix in range(len(line_points)):
        #     if pix > 0:
        #         dblr.draw_transformed_line(
        #                 line_points[pix - 1], line_points[pix], mn.Color4.yellow()
        #             )

    def draw_event(
        self,
        simulation_call: Optional[Callable] = None,
        global_call: Optional[Callable] = None,
        active_agent_id_and_sensor_name: Tuple[int, str] = (0, "color_sensor"),
    ) -> None:
        """
        Calls continuously to re-render frames and swap the two frame buffers
        at a fixed rate.
        """
        agent_acts_per_sec = self.fps

        mn.gl.default_framebuffer.clear(
            mn.gl.FramebufferClear.COLOR | mn.gl.FramebufferClear.DEPTH
        )

        # Agent actions should occur at a fixed rate per second
        self.time_since_last_simulation += Timer.prev_frame_duration
        num_agent_actions: int = self.time_since_last_simulation * agent_acts_per_sec
        self.move_and_look(int(num_agent_actions))

        # Occasionally a frame will pass quicker than 1/60 seconds
        if self.time_since_last_simulation >= 1.0 / self.fps:
            if self.simulating or self.simulate_single_step:
                self.sim.step_world(1.0 / self.fps)
                self.simulate_single_step = False
                if simulation_call is not None:
                    simulation_call()
                self.update_humanoid()
            if global_call is not None:
                global_call()

            # reset time_since_last_simulation, accounting for potential overflow
            self.time_since_last_simulation = math.fmod(
                self.time_since_last_simulation, 1.0 / self.fps
            )
            self.record_obs(self.obs_buffer)

        if (
            self.sim.get_world_time() - self.humanoid_model_last_inc
            > self.humanoid_model_inc_freq
        ):
            self.inc_humanoid()
            self.humanoid_model_last_inc = self.sim.get_world_time()
            self.humanoid_model_inc_freq = max(
                0.25, self.humanoid_model_inc_freq * 0.75
            )

        if self.sim.get_world_time() > 20:
            self.save_video(
                filename="test_video_out.mp4", buffer=self.obs_buffer, fps=self.fps
            )
            exit()

        if self.enable_batch_renderer:
            self.render_batch()
        else:
            pass
            # self.sim._Simulator__sensors[keys[0]][keys[1]].draw_observation()
            # agent = self.sim.get_agent(keys[0])
            # self.render_camera = agent.scene_node.node_sensor_suite.get(keys[1])
            # self.debug_draw()
            self.render_camera.render_target.blit_rgba_to_default()

        # draw CPU/GPU usage data and other info to the app window
        mn.gl.default_framebuffer.bind()
        self.draw_text(self.render_camera.specification())

        self.swap_buffers()
        Timer.next_frame()
        self.redraw()

    def default_agent_config(self) -> habitat_sim.agent.AgentConfiguration:
        """
        Set up our own agent and agent controls
        """
        make_action_spec = habitat_sim.agent.ActionSpec
        make_actuation_spec = habitat_sim.agent.ActuationSpec
        MOVE, LOOK = 0.07, 1.5

        # all of our possible actions' names
        action_list = [
            "move_left",
            "turn_left",
            "move_right",
            "turn_right",
            "move_backward",
            "look_up",
            "move_forward",
            "look_down",
            "move_down",
            "move_up",
        ]

        action_space: Dict[str, habitat_sim.agent.ActionSpec] = {}

        # build our action space map
        for action in action_list:
            actuation_spec_amt = MOVE if "move" in action else LOOK
            action_spec = make_action_spec(
                action, make_actuation_spec(actuation_spec_amt)
            )
            action_space[action] = action_spec

        sensor_spec: List[habitat_sim.sensor.SensorSpec] = self.cfg.agents[
            self.agent_id
        ].sensor_specifications

        agent_config = habitat_sim.agent.AgentConfiguration(
            height=1.5,
            radius=0.3,
            sensor_specifications=sensor_spec,
            action_space=action_space,
            body_type="cylinder",
        )
        return agent_config

    def reconfigure_sim(self) -> None:
        """
        Utilizes the current `self.sim_settings` to configure and set up a new
        `habitat_sim.Simulator`, and then either starts a simulation instance, or replaces
        the current simulator instance, reloading the most recently loaded scene
        """
        # configure our sim_settings but then set the agent to our default
        self.cfg = make_cfg(self.sim_settings)
        self.agent_id: int = self.sim_settings["default_agent"]
        self.cfg.agents[self.agent_id] = self.default_agent_config()

        if self.enable_batch_renderer:
            self.cfg.enable_batch_renderer = True
            self.cfg.sim_cfg.create_renderer = False
            self.cfg.sim_cfg.enable_gfx_replay_save = True

        if self.sim_settings["use_default_lighting"]:
            logger.info("Setting default lighting override for scene.")
            self.cfg.sim_cfg.override_scene_light_defaults = True
            self.cfg.sim_cfg.scene_light_setup = habitat_sim.gfx.DEFAULT_LIGHTING_KEY

        if self.sim is None:
            self.tiled_sims = []
            for _i in range(self.num_env):
                self.tiled_sims.append(habitat_sim.Simulator(self.cfg))
            self.sim = self.tiled_sims[0]
        else:  # edge case
            for i in range(self.num_env):
                if (
                    self.tiled_sims[i].config.sim_cfg.scene_id
                    == self.cfg.sim_cfg.scene_id
                ):
                    # we need to force a reset, so change the internal config scene name
                    self.tiled_sims[i].config.sim_cfg.scene_id = "NONE"
                self.tiled_sims[i].reconfigure(self.cfg)

        # post reconfigure
        self.default_agent = self.sim.get_agent(self.agent_id)
        self.render_camera = self.default_agent.scene_node.node_sensor_suite.get(
            "color_sensor"
        )

        # set sim_settings scene name as actual loaded scene
        self.sim_settings["scene"] = self.sim.curr_scene_name

        # Initialize replay renderer
        if self.enable_batch_renderer and self.replay_renderer is None:
            self.replay_renderer_cfg = ReplayRendererConfiguration()
            self.replay_renderer_cfg.num_environments = self.num_env
            self.replay_renderer_cfg.standalone = (
                False  # Context is owned by the GLFW window
            )
            self.replay_renderer_cfg.sensor_specifications = self.cfg.agents[
                self.agent_id
            ].sensor_specifications
            self.replay_renderer_cfg.gpu_device_id = self.cfg.sim_cfg.gpu_device_id
            self.replay_renderer_cfg.force_separate_semantic_scene_graph = False
            self.replay_renderer_cfg.leave_context_with_background_renderer = False
            self.replay_renderer = ReplayRenderer.create_batch_replay_renderer(
                self.replay_renderer_cfg
            )
            # Pre-load composite files
            if sim_settings["composite_files"] is not None:
                for composite_file in sim_settings["composite_files"]:
                    self.replay_renderer.preload_file(composite_file)

        Timer.start()
        self.step = -1

    def render_batch(self):
        """
        This method updates the replay manager with the current state of environments and renders them.
        """
        for i in range(self.num_env):
            # Apply keyframe
            keyframe = self.tiled_sims[i].gfx_replay_manager.extract_keyframe()
            self.replay_renderer.set_environment_keyframe(i, keyframe)
            # Copy sensor transforms
            sensor_suite = self.tiled_sims[i]._sensors
            for sensor_uuid, sensor in sensor_suite.items():
                transform = sensor._sensor_object.node.absolute_transformation()
                self.replay_renderer.set_sensor_transform(i, sensor_uuid, transform)
            # Render
            self.replay_renderer.render(mn.gl.default_framebuffer)

    def move_and_look(self, repetitions: int) -> None:
        """
        This method is called continuously with `self.draw_event` to monitor
        any changes in the movement keys map `Dict[KeyEvent.key, Bool]`.
        When a key in the map is set to `True` the corresponding action is taken.
        """
        # avoids unnecessary updates to grabber's object position
        if repetitions == 0:
            return

        key = Application.KeyEvent.Key
        agent = self.sim.agents[self.agent_id]
        press: Dict[key.key, bool] = self.pressed
        act: Dict[key.key, str] = self.key_to_action

        action_queue: List[str] = [act[k] for k, v in press.items() if v]

        for _ in range(int(repetitions)):
            [agent.act(x) for x in action_queue]

        # update the grabber transform when our agent is moved
        if self.mouse_grabber is not None:
            # update location of grabbed object
            self.update_grab_position(self.previous_mouse_point)

    def invert_gravity(self) -> None:
        """
        Sets the gravity vector to the negative of it's previous value. This is
        a good method for testing simulation functionality.
        """
        gravity: mn.Vector3 = self.sim.get_gravity() * -1
        self.sim.set_gravity(gravity)

    def key_press_event(self, event: Application.KeyEvent) -> None:
        """
        Handles `Application.KeyEvent` on a key press by performing the corresponding functions.
        If the key pressed is part of the movement keys map `Dict[KeyEvent.key, Bool]`, then the
        key will be set to False for the next `self.move_and_look()` to update the current actions.
        """
        key = event.key
        pressed = Application.KeyEvent.Key
        mod = Application.InputEvent.Modifier

        shift_pressed = bool(event.modifiers & mod.SHIFT)
        alt_pressed = bool(event.modifiers & mod.ALT)
        # warning: ctrl doesn't always pass through with other key-presses

        if key == pressed.ESC:
            event.accepted = True
            self.exit_event(Application.ExitEvent)
            return

        elif key == pressed.H:
            self.print_help_text()

        elif key == pressed.TAB:
            # NOTE: (+ALT) - reconfigure without cycling scenes
            if not alt_pressed:
                # cycle the active scene from the set available in MetadataMediator
                inc = -1 if shift_pressed else 1
                scene_ids = self.sim.metadata_mediator.get_scene_handles()
                cur_scene_index = 0
                if self.sim_settings["scene"] not in scene_ids:
                    matching_scenes = [
                        (ix, x)
                        for ix, x in enumerate(scene_ids)
                        if self.sim_settings["scene"] in x
                    ]
                    if not matching_scenes:
                        logger.warning(
                            f"The current scene, '{self.sim_settings['scene']}', is not in the list, starting cycle at index 0."
                        )
                    else:
                        cur_scene_index = matching_scenes[0][0]
                else:
                    cur_scene_index = scene_ids.index(self.sim_settings["scene"])

                next_scene_index = min(
                    max(cur_scene_index + inc, 0), len(scene_ids) - 1
                )
                self.sim_settings["scene"] = scene_ids[next_scene_index]
            self.reconfigure_sim()
            # compute NavMesh if not already loaded by the scene.
            self.navmesh_config_and_recompute()

            self.largest_indoor_island = get_largest_island_index(
                self.sim.pathfinder, self.sim, allow_outdoor=False
            )
            logger.info(
                f"Reconfigured simulator for scene: {self.sim_settings['scene']}"
            )
            self.prev_humanoid_base_state = None
            self.humanoid = None
            self.humanoid_cur_path = None
            self.humanoid_cur_waypoint = 0
            self.init_humanoid(self.humanoid_models[self.humanoid_cur_model_index])

        elif key == pressed.SPACE:
            if not self.sim.config.sim_cfg.enable_physics:
                logger.warn("Warning: physics was not enabled during setup")
            else:
                self.simulating = not self.simulating
                logger.info(f"Command: physics simulating set to {self.simulating}")

        elif key == pressed.PERIOD:
            if self.simulating:
                logger.warn("Warning: physics simulation already running")
            else:
                self.simulate_single_step = True
                logger.info("Command: physics step taken")

        elif key == pressed.COMMA:
            self.debug_bullet_draw = not self.debug_bullet_draw
            logger.info(f"Command: toggle Bullet debug draw: {self.debug_bullet_draw}")

        elif key == pressed.C:
            if shift_pressed:
                self.contact_debug_draw = not self.contact_debug_draw
                logger.info(
                    f"Command: toggle contact debug draw: {self.contact_debug_draw}"
                )
            else:
                # perform a discrete collision detection pass and enable contact debug drawing to visualize the results
                logger.info(
                    "Command: perform discrete collision detection and visualize active contacts."
                )
                self.sim.perform_discrete_collision_detection()
                self.contact_debug_draw = True
                # TODO: add a nice log message with concise contact pair naming.

        elif key == pressed.T:
            # load URDF
            fixed_base = alt_pressed
            urdf_file_path = ""
            if shift_pressed and self.cached_urdf:
                urdf_file_path = self.cached_urdf
            else:
                urdf_file_path = input("Load URDF: provide a URDF filepath:").strip()

            if not urdf_file_path:
                logger.warn("Load URDF: no input provided. Aborting.")
            elif not urdf_file_path.endswith((".URDF", ".urdf")):
                logger.warn("Load URDF: input is not a URDF. Aborting.")
            elif os.path.exists(urdf_file_path):
                self.cached_urdf = urdf_file_path
                aom = self.sim.get_articulated_object_manager()
                ao = aom.add_articulated_object_from_urdf(
                    urdf_file_path,
                    fixed_base,
                    1.0,
                    1.0,
                    True,
                    maintain_link_order=False,
                    intertia_from_urdf=False,
                )
                ao.translation = (
                    self.default_agent.scene_node.transformation.transform_point(
                        [0.0, 1.0, -1.5]
                    )
                )
                # check removal and auto-creation
                joint_motor_settings = habitat_sim.physics.JointMotorSettings(
                    position_target=0.0,
                    position_gain=1.0,
                    velocity_target=0.0,
                    velocity_gain=1.0,
                    max_impulse=1000.0,
                )
                existing_motor_ids = ao.existing_joint_motor_ids
                for motor_id in existing_motor_ids:
                    ao.remove_joint_motor(motor_id)
                ao.create_all_motors(joint_motor_settings)
            else:
                logger.warn("Load URDF: input file not found. Aborting.")

        elif key == pressed.M:
            self.cycle_mouse_mode()
            logger.info(f"Command: mouse mode set to {self.mouse_interaction}")

        elif key == pressed.V:
            # self.invert_gravity()
            # logger.info("Command: gravity inverted")
            # self.update_humanoid()
            controller = random.choice([HumanoidRearrangeController, SeqPoseController])
            controller = HumanoidRearrangeController
            # model = random.choice(self.humanoid_models)
            self.humanoid_cur_model_index = (self.humanoid_cur_model_index + 1) % len(
                self.humanoid_models
            )
            model = self.humanoid_models[self.humanoid_cur_model_index]
            if controller == SeqPoseController:
                model = (model[0], random.choice(self.humanoid_seq_motions))
            # model = self.humanoid_models[0]
            # print(model)
            self.init_humanoid(model, controller=controller)

        elif key == pressed.B:
            self.save_video(
                filename="test_video_out.mp4", buffer=self.obs_buffer, fps=self.fps
            )

        elif key == pressed.N:
            # (default) - toggle navmesh visualization
            # NOTE: (+ALT) - re-sample the agent position on the NavMesh
            # NOTE: (+SHIFT) - re-compute the NavMesh
            if alt_pressed:
                logger.info("Command: resample agent state from navmesh")
                if self.sim.pathfinder.is_loaded:
                    new_agent_state = habitat_sim.AgentState()
                    new_agent_state.position = (
                        self.sim.pathfinder.get_random_navigable_point()
                    )
                    new_agent_state.rotation = quat_from_angle_axis(
                        self.sim.random.uniform_float(0, 2.0 * np.pi),
                        np.array([0, 1, 0]),
                    )
                    self.default_agent.set_state(new_agent_state)
                else:
                    logger.warning(
                        "NavMesh is not initialized. Cannot sample new agent state."
                    )
            elif shift_pressed:
                logger.info("Command: recompute navmesh")
                self.navmesh_config_and_recompute()
            else:
                if self.sim.pathfinder.is_loaded:
                    self.sim.navmesh_visualization = not self.sim.navmesh_visualization
                    logger.info("Command: toggle navmesh")
                else:
                    logger.warn("Warning: recompute navmesh first")

        # update map of moving/looking keys which are currently pressed
        if key in self.pressed:
            self.pressed[key] = True
        event.accepted = True
        self.redraw()

    def record_obs(self, buffer: List[Any]):
        """
        Record an observation from the camera into a buffer.
        """

        # if self.humanoid is not None:
        #     self.render_camera.node.transformation = mn.Matrix4.identity_init()
        #     # print(self.humanoid.base_transformation)
        #     # print(self.humanoid.base_rot)
        #     self.default_agent.scene_node.transformation = mn.Matrix4.look_at(
        #         # eye = self.humanoid.sim_obj.transformation.transform_point(mn.Vector3(0.7,1.2,0.55)),
        #         # eye = self.humanoid.sim_obj.transformation.translation + mn.Vector3(0.7,1.2,0.55),
        #         eye=self.humanoid.base_pos + mn.Vector3(1.0, 2.0, 0.55),
        #         # eye = self.humanoid.base_pos + base_rot_quat.transform_vector(mn.Vector3(0.7,2.0,0.55)),
        #         target=self.humanoid.base_pos + mn.Vector3(0, 1.3, 0),
        #         up=mn.Vector3(0, 1.0, 0),
        #     )

        self.follow_cam.update_state()
        self.render_camera.node.transformation = mn.Matrix4.identity_init()
        self.default_agent.scene_node.translation = self.follow_cam.cur_pos
        self.default_agent.scene_node.rotation = self.follow_cam.cur_orient

        # active_agent_id_and_sensor_name: Tuple[int, str] = (0, "color_sensor")
        # self.sim._Simulator__sensors[active_agent_id_and_sensor_name[0]][
        #    active_agent_id_and_sensor_name[1]
        # ].draw_observation()

        buffer.append(self.sim.get_sensor_observations())
        # self.render_camera.node.transformation = prev_transform
        # self.default_agent.scene_node.transformation = prev_agent_transform

    def save_video(self, filename: str, buffer: List[Any], fps: int = 60):
        """
        Save a video with the frames from the buffer.
        """
        habitat_sim.utils.viz_utils.make_video(
            observations=buffer,
            primary_obs="color_sensor",
            primary_obs_type="color",
            video_file=filename,
            fps=fps,
        )

    def key_release_event(self, event: Application.KeyEvent) -> None:
        """
        Handles `Application.KeyEvent` on a key release. When a key is released, if it
        is part of the movement keys map `Dict[KeyEvent.key, Bool]`, then the key will
        be set to False for the next `self.move_and_look()` to update the current actions.
        """
        key = event.key

        # update map of moving/looking keys which are currently pressed
        if key in self.pressed:
            self.pressed[key] = False
        event.accepted = True
        self.redraw()

    def mouse_move_event(self, event: Application.MouseMoveEvent) -> None:
        """
        Handles `Application.MouseMoveEvent`. When in LOOK mode, enables the left
        mouse button to steer the agent's facing direction. When in GRAB mode,
        continues to update the grabber's object position with our agents position.
        """
        button = Application.MouseMoveEvent.Buttons
        # if interactive mode -> LOOK MODE
        if event.buttons == button.LEFT and self.mouse_interaction == MouseMode.LOOK:
            agent = self.sim.agents[self.agent_id]
            delta = self.get_mouse_position(event.relative_position) / 2
            action = habitat_sim.agent.ObjectControls()
            act_spec = habitat_sim.agent.ActuationSpec

            # left/right on agent scene node
            action(agent.scene_node, "turn_right", act_spec(delta.x))

            # up/down on cameras' scene nodes
            action = habitat_sim.agent.ObjectControls()
            sensors = list(self.default_agent.scene_node.subtree_sensors.values())
            [action(s.object, "look_down", act_spec(delta.y), False) for s in sensors]

        # if interactive mode is TRUE -> GRAB MODE
        elif self.mouse_interaction == MouseMode.GRAB and self.mouse_grabber:
            # update location of grabbed object
            self.update_grab_position(self.get_mouse_position(event.position))

        self.previous_mouse_point = self.get_mouse_position(event.position)
        self.redraw()
        event.accepted = True

    def mouse_press_event(self, event: Application.MouseEvent) -> None:
        """
        Handles `Application.MouseEvent`. When in GRAB mode, click on
        objects to drag their position. (right-click for fixed constraints)
        """
        button = Application.MouseEvent.Button
        physics_enabled = self.sim.get_physics_simulation_library()

        # if interactive mode is True -> GRAB MODE
        if self.mouse_interaction == MouseMode.GRAB and physics_enabled:
            render_camera = self.render_camera.render_camera
            ray = render_camera.unproject(self.get_mouse_position(event.position))
            raycast_results = self.sim.cast_ray(ray=ray)

            if raycast_results.has_hits():
                hit_object, ao_link = -1, -1
                hit_info = raycast_results.hits[0]

                if hit_info.object_id >= 0:
                    # we hit an non-staged collision object
                    ro_mngr = self.sim.get_rigid_object_manager()
                    ao_mngr = self.sim.get_articulated_object_manager()
                    ao = ao_mngr.get_object_by_id(hit_info.object_id)
                    ro = ro_mngr.get_object_by_id(hit_info.object_id)

                    if ro:
                        # if grabbed an object
                        hit_object = hit_info.object_id
                        object_pivot = ro.transformation.inverted().transform_point(
                            hit_info.point
                        )
                        object_frame = ro.rotation.inverted()
                    elif ao:
                        # if grabbed the base link
                        hit_object = hit_info.object_id
                        object_pivot = ao.transformation.inverted().transform_point(
                            hit_info.point
                        )
                        object_frame = ao.rotation.inverted()
                    else:
                        for ao_handle in ao_mngr.get_objects_by_handle_substring():
                            ao = ao_mngr.get_object_by_handle(ao_handle)
                            link_to_obj_ids = ao.link_object_ids

                            if hit_info.object_id in link_to_obj_ids:
                                # if we got a link
                                ao_link = link_to_obj_ids[hit_info.object_id]
                                object_pivot = (
                                    ao.get_link_scene_node(ao_link)
                                    .transformation.inverted()
                                    .transform_point(hit_info.point)
                                )
                                object_frame = ao.get_link_scene_node(
                                    ao_link
                                ).rotation.inverted()
                                hit_object = ao.object_id
                                break
                    # done checking for AO

                    if hit_object >= 0:
                        node = self.default_agent.scene_node
                        constraint_settings = physics.RigidConstraintSettings()

                        constraint_settings.object_id_a = hit_object
                        constraint_settings.link_id_a = ao_link
                        constraint_settings.pivot_a = object_pivot
                        constraint_settings.frame_a = (
                            object_frame.to_matrix() @ node.rotation.to_matrix()
                        )
                        constraint_settings.frame_b = node.rotation.to_matrix()
                        constraint_settings.pivot_b = hit_info.point

                        # by default use a point 2 point constraint
                        if event.button == button.RIGHT:
                            constraint_settings.constraint_type = (
                                physics.RigidConstraintType.Fixed
                            )

                        grip_depth = (
                            hit_info.point - render_camera.node.absolute_translation
                        ).length()

                        self.mouse_grabber = MouseGrabber(
                            constraint_settings,
                            grip_depth,
                            self.sim,
                        )
                    else:
                        logger.warn("Oops, couldn't find the hit object. That's odd.")
                # end if didn't hit the scene
            # end has raycast hit
        # end has physics enabled

        self.previous_mouse_point = self.get_mouse_position(event.position)
        self.redraw()
        event.accepted = True

    def mouse_scroll_event(self, event: Application.MouseScrollEvent) -> None:
        """
        Handles `Application.MouseScrollEvent`. When in LOOK mode, enables camera
        zooming (fine-grained zoom using shift) When in GRAB mode, adjusts the depth
        of the grabber's object. (larger depth change rate using shift)
        """
        scroll_mod_val = (
            event.offset.y
            if abs(event.offset.y) > abs(event.offset.x)
            else event.offset.x
        )
        if not scroll_mod_val:
            return

        # use shift to scale action response
        shift_pressed = bool(event.modifiers & Application.InputEvent.Modifier.SHIFT)
        alt_pressed = bool(event.modifiers & Application.InputEvent.Modifier.ALT)
        ctrl_pressed = bool(event.modifiers & Application.InputEvent.Modifier.CTRL)

        # if interactive mode is False -> LOOK MODE
        if self.mouse_interaction == MouseMode.LOOK:
            # use shift for fine-grained zooming
            mod_val = 1.01 if shift_pressed else 1.1
            mod = mod_val if scroll_mod_val > 0 else 1.0 / mod_val
            cam = self.render_camera
            cam.zoom(mod)
            self.redraw()

        elif self.mouse_interaction == MouseMode.GRAB and self.mouse_grabber:
            # adjust the depth
            mod_val = 0.1 if shift_pressed else 0.01
            scroll_delta = scroll_mod_val * mod_val
            if alt_pressed or ctrl_pressed:
                # rotate the object's local constraint frame
                agent_t = self.default_agent.scene_node.transformation_matrix()
                # ALT - yaw
                rotation_axis = agent_t.transform_vector(mn.Vector3(0, 1, 0))
                if alt_pressed and ctrl_pressed:
                    # ALT+CTRL - roll
                    rotation_axis = agent_t.transform_vector(mn.Vector3(0, 0, -1))
                elif ctrl_pressed:
                    # CTRL - pitch
                    rotation_axis = agent_t.transform_vector(mn.Vector3(1, 0, 0))
                self.mouse_grabber.rotate_local_frame_by_global_angle_axis(
                    rotation_axis, mn.Rad(scroll_delta)
                )
            else:
                # update location of grabbed object
                self.mouse_grabber.grip_depth += scroll_delta
                self.update_grab_position(self.get_mouse_position(event.position))
        self.redraw()
        event.accepted = True

    def mouse_release_event(self, event: Application.MouseEvent) -> None:
        """
        Release any existing constraints.
        """
        del self.mouse_grabber
        self.mouse_grabber = None
        event.accepted = True

    def update_grab_position(self, point: mn.Vector2i) -> None:
        """
        Accepts a point derived from a mouse click event and updates the
        transform of the mouse grabber.
        """
        # check mouse grabber
        if not self.mouse_grabber:
            return

        render_camera = self.render_camera.render_camera
        ray = render_camera.unproject(point)

        rotation: mn.Matrix3x3 = self.default_agent.scene_node.rotation.to_matrix()
        translation: mn.Vector3 = (
            render_camera.node.absolute_translation
            + ray.direction * self.mouse_grabber.grip_depth
        )
        self.mouse_grabber.update_transform(mn.Matrix4.from_(rotation, translation))

    def get_mouse_position(self, mouse_event_position: mn.Vector2i) -> mn.Vector2i:
        """
        This function will get a screen-space mouse position appropriately
        scaled based on framebuffer size and window size.  Generally these would be
        the same value, but on certain HiDPI displays (Retina displays) they may be
        different.
        """
        scaling = mn.Vector2i(self.framebuffer_size) / mn.Vector2i(self.window_size)
        return mouse_event_position * scaling

    def cycle_mouse_mode(self) -> None:
        """
        This method defines how to cycle through the mouse mode.
        """
        if self.mouse_interaction == MouseMode.LOOK:
            self.mouse_interaction = MouseMode.GRAB
        elif self.mouse_interaction == MouseMode.GRAB:
            self.mouse_interaction = MouseMode.LOOK

    def navmesh_config_and_recompute(self) -> None:
        """
        This method is setup to be overridden in for setting config accessibility
        in inherited classes.
        """
        self.navmesh_settings = habitat_sim.NavMeshSettings()
        self.navmesh_settings.set_defaults()
        self.navmesh_settings.agent_height = self.cfg.agents[self.agent_id].height
        self.navmesh_settings.agent_radius = self.cfg.agents[self.agent_id].radius
        self.navmesh_settings.include_static_objects = True
        self.sim.recompute_navmesh(
            self.sim.pathfinder,
            self.navmesh_settings,
        )

    def exit_event(self, event: Application.ExitEvent):
        """
        Overrides exit_event to properly close the Simulator before exiting the
        application.
        """
        for i in range(self.num_env):
            self.tiled_sims[i].close(destroy=True)
            event.accepted = True
        exit(0)

    def draw_text(self, sensor_spec):
        return
        self.shader.bind_vector_texture(self.glyph_cache.texture)
        self.shader.transformation_projection_matrix = self.window_text_transform
        self.shader.color = [1.0, 1.0, 1.0]

        sensor_type_string = str(sensor_spec.sensor_type.name)
        sensor_subtype_string = str(sensor_spec.sensor_subtype.name)
        if self.mouse_interaction == MouseMode.LOOK:
            mouse_mode_string = "LOOK"
        elif self.mouse_interaction == MouseMode.GRAB:
            mouse_mode_string = "GRAB"
        self.window_text.render(
            f"""
{self.fps} FPS
Sensor Type: {sensor_type_string}
Sensor Subtype: {sensor_subtype_string}
Mouse Interaction Mode: {mouse_mode_string}
            """
        )
        self.shader.draw(self.window_text.mesh)

    def print_help_text(self) -> None:
        """
        Print the Key Command help text.
        """
        logger.info(
            """
=====================================================
Welcome to the Habitat-sim Python Viewer application!
=====================================================
Mouse Functions ('m' to toggle mode):
----------------
In LOOK mode (default):
    LEFT:
        Click and drag to rotate the agent and look up/down.
    WHEEL:
        Modify orthographic camera zoom/perspective camera FOV (+SHIFT for fine grained control)

In GRAB mode (with 'enable-physics'):
    LEFT:
        Click and drag to pickup and move an object with a point-to-point constraint (e.g. ball joint).
    RIGHT:
        Click and drag to pickup and move an object with a fixed frame constraint.
    WHEEL (with picked object):
        default - Pull gripped object closer or push it away.
        (+ALT) rotate object fixed constraint frame (yaw)
        (+CTRL) rotate object fixed constraint frame (pitch)
        (+ALT+CTRL) rotate object fixed constraint frame (roll)
        (+SHIFT) amplify scroll magnitude


Key Commands:
-------------
    esc:        Exit the application.
    'h':        Display this help message.
    'm':        Cycle mouse interaction modes.

    Agent Controls:
    'wasd':     Move the agent's body forward/backward and left/right.
    'zx':       Move the agent's body up/down.
    arrow keys: Turn the agent's body left/right and camera look up/down.

    Utilities:
    'r':        Reset the simulator with the most recently loaded scene.
    'n':        Show/hide NavMesh wireframe.
                (+SHIFT) Recompute NavMesh with default settings.
                (+ALT) Re-sample the agent(camera)'s position and orientation from the NavMesh.
    ',':        Render a Bullet collision shape debug wireframe overlay (white=active, green=sleeping, blue=wants sleeping, red=can't sleep).
    'c':        Run a discrete collision detection pass and render a debug wireframe overlay showing active contact points and normals (yellow=fixed length normals, red=collision distances).
                (+SHIFT) Toggle the contact point debug render overlay on/off.

    Object Interactions:
    SPACE:      Toggle physics simulation on/off.
    '.':        Take a single simulation step if not simulating continuously.
    'v':        (physics) Invert gravity.
    't':        Load URDF from filepath
                (+SHIFT) quick re-load the previously specified URDF
                (+ALT) load the URDF with fixed base
=====================================================
"""
        )


class MouseMode(Enum):
    LOOK = 0
    GRAB = 1
    MOTION = 2


class MouseGrabber:
    """
    Create a MouseGrabber from RigidConstraintSettings to manipulate objects.
    """

    def __init__(
        self,
        settings: physics.RigidConstraintSettings,
        grip_depth: float,
        sim: habitat_sim.simulator.Simulator,
    ) -> None:
        self.settings = settings
        self.simulator = sim

        # defines distance of the grip point from the camera for pivot updates
        self.grip_depth = grip_depth
        self.constraint_id = sim.create_rigid_constraint(settings)

    def __del__(self):
        self.remove_constraint()

    def remove_constraint(self) -> None:
        """
        Remove a rigid constraint by id.
        """
        self.simulator.remove_rigid_constraint(self.constraint_id)

    def updatePivot(self, pos: mn.Vector3) -> None:
        self.settings.pivot_b = pos
        self.simulator.update_rigid_constraint(self.constraint_id, self.settings)

    def update_frame(self, frame: mn.Matrix3x3) -> None:
        self.settings.frame_b = frame
        self.simulator.update_rigid_constraint(self.constraint_id, self.settings)

    def update_transform(self, transform: mn.Matrix4) -> None:
        self.settings.frame_b = transform.rotation()
        self.settings.pivot_b = transform.translation
        self.simulator.update_rigid_constraint(self.constraint_id, self.settings)

    def rotate_local_frame_by_global_angle_axis(
        self, axis: mn.Vector3, angle: mn.Rad
    ) -> None:
        """rotate the object's local constraint frame with a global angle axis input."""
        object_transform = mn.Matrix4()
        rom = self.simulator.get_rigid_object_manager()
        aom = self.simulator.get_articulated_object_manager()
        if rom.get_library_has_id(self.settings.object_id_a):
            object_transform = rom.get_object_by_id(
                self.settings.object_id_a
            ).transformation
        else:
            # must be an ao
            object_transform = (
                aom.get_object_by_id(self.settings.object_id_a)
                .get_link_scene_node(self.settings.link_id_a)
                .transformation
            )
        local_axis = object_transform.inverted().transform_vector(axis)
        R = mn.Matrix4.rotation(angle, local_axis.normalized())
        self.settings.frame_a = R.rotation().__matmul__(self.settings.frame_a)
        self.simulator.update_rigid_constraint(self.constraint_id, self.settings)


class Timer:
    """
    Timer class used to keep track of time between buffer swaps
    and guide the display frame rate.
    """

    start_time = 0.0
    prev_frame_time = 0.0
    prev_frame_duration = 0.0
    running = False

    @staticmethod
    def start() -> None:
        """
        Starts timer and resets previous frame time to the start time.
        """
        Timer.running = True
        Timer.start_time = time.time()
        Timer.prev_frame_time = Timer.start_time
        Timer.prev_frame_duration = 0.0

    @staticmethod
    def stop() -> None:
        """
        Stops timer and erases any previous time data, resetting the timer.
        """
        Timer.running = False
        Timer.start_time = 0.0
        Timer.prev_frame_time = 0.0
        Timer.prev_frame_duration = 0.0

    @staticmethod
    def next_frame() -> None:
        """
        Records previous frame duration and updates the previous frame timestamp
        to the current time. If the timer is not currently running, perform nothing.
        """
        if not Timer.running:
            return
        Timer.prev_frame_duration = time.time() - Timer.prev_frame_time
        Timer.prev_frame_time = time.time()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()

    # optional arguments
    parser.add_argument(
        "--scene",
        default="./data/test_assets/scenes/simple_room.glb",
        type=str,
        help='scene/stage file to load (default: "./data/test_assets/scenes/simple_room.glb")',
    )
    parser.add_argument(
        "--dataset",
        default="./data/objects/ycb/ycb.scene_dataset_config.json",
        type=str,
        metavar="DATASET",
        help='dataset configuration file to use (default: "./data/objects/ycb/ycb.scene_dataset_config.json")',
    )
    parser.add_argument(
        "--disable-physics",
        action="store_true",
        help="disable physics simulation (default: False)",
    )
    parser.add_argument(
        "--use-default-lighting",
        action="store_true",
        help="Override configured lighting to use default lighting for the stage.",
    )
    parser.add_argument(
        "--ibl",
        action="store_true",
        help="Enable image-based lighting. Only applicable to scenes built with PBR materials.",
    )
    parser.add_argument(
        "--hbao",
        action="store_true",
        help="Enable horizon-based ambient occlusion.",
    )
    parser.add_argument(
        "--enable-batch-renderer",
        action="store_true",
        help="Enable batch rendering mode. The number of concurrent environments is specified with the num-environments parameter.",
    )
    parser.add_argument(
        "--num-environments",
        default=1,
        type=int,
        help="Number of concurrent environments to batch render. Note that only the first environment simulates physics and can be controlled.",
    )
    parser.add_argument(
        "--composite-files",
        type=str,
        nargs="*",
        help="Composite files that the batch renderer will use in-place of simulation assets to improve memory usage and performance. If none is specified, the original scene files will be loaded from disk.",
    )
    parser.add_argument(
        "--width",
        default=800,
        type=int,
        help="Horizontal resolution of the window.",
    )
    parser.add_argument(
        "--height",
        default=600,
        type=int,
        help="Vertical resolution of the window.",
    )

    args = parser.parse_args()

    if args.num_environments < 1:
        parser.error("num-environments must be a positive non-zero integer.")
    if args.width < 1:
        parser.error("width must be a positive non-zero integer.")
    if args.height < 1:
        parser.error("height must be a positive non-zero integer.")

    # Setting up sim_settings
    sim_settings: Dict[str, Any] = default_sim_settings
    sim_settings["scene"] = args.scene
    sim_settings["scene_dataset_config_file"] = args.dataset
    sim_settings["enable_physics"] = not args.disable_physics
    sim_settings["use_default_lighting"] = args.use_default_lighting
    sim_settings["enable_batch_renderer"] = args.enable_batch_renderer
    sim_settings["num_environments"] = args.num_environments
    sim_settings["composite_files"] = args.composite_files
    sim_settings["window_width"] = args.width
    sim_settings["window_height"] = args.height
    sim_settings["pbr_image_based_lighting"] = args.ibl
    sim_settings["default_agent_navmesh"] = False
    sim_settings["hbao_visual_effects"] = args.hbao

    # start the application
    HabitatSimInteractiveViewer(sim_settings).exec()
