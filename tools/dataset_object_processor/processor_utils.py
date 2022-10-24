# Copyright (c) Facebook, Inc. and its affiliates.
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import argparse
import csv
import datetime
import os
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import magnum as mn
from processor_settings import make_cfg

import habitat_sim as hsim
from habitat_sim import physics
from habitat_sim.agent.agent import Agent
from habitat_sim.utils import viz_utils as vut

# A line of dashes to divide sections of terminal output
section_divider: str = "\n" + "-" * 72


class DatasetProcessorSim(hsim.Simulator):
    """ """

    sim_settings: Dict[str, Any] = None

    # indicates if we are logging, either during the normal execution of the
    # simulation, or if we are debugging. Are overriden from config file
    silent: bool = True
    debug_print: bool = False

    default_agent: Agent = None

    # stores info about current rigid object displayed and its render/collision
    # mesh asset names
    curr_obj: physics.ManagedBulletRigidObject = None
    render_asset_handle: str = None
    collision_asset_handle: str = None

    # so that we can easily reset the agent to its default transform
    default_agent_pos: mn.Vector3 = None
    default_agent_rot: mn.Quaternion = None

    # so that we can easily reset the rigid objects to their default transforms
    default_obj_pos: mn.Vector3 = None
    default_obj_rot: mn.Quaternion = None

    # indicates if we are making a video recording, and which is the current recording
    # task we are drawing. Possible values are "draw_bbox", "draw_collision_asset",
    # and "draw_physics"
    draw_task: str = None
    observations = []

    def debug_draw(self, sensor_uuid: Optional[str] = None) -> None:
        r"""Override method in habitat_sim.Simulator class to add optional,
        application specific debug line drawing commands to the sensor output.
        See Simulator.get_debug_line_render().
        :param sensor_uuid: The uuid of the sensor being rendered to optionally
        limit debug drawing to specific visualizations (e.g. a third person eval camera)
        """
        # determine which task we are drawing and call the associated function
        if self.draw_task == "draw_bbox":
            self.draw_bbox()
        elif self.draw_task == "draw_collision_asset_wireframe":
            self.draw_collision_asset_wireframe(sensor_uuid)
        elif self.draw_task == "draw_physics":
            self.draw_physics()

    def draw_bbox(self) -> None:
        """ """
        # self.set_object_bb_draw(True, self.curr_obj.object_id)
        rgb = self.sim_settings["bbox_rgb"]
        line_color = mn.Color4.from_xyz(rgb)
        bb_corners: List[mn.Vector3] = get_bounding_box_corners(self.curr_obj)
        num_corners = len(bb_corners)
        self.get_debug_line_render().set_line_width(0.01)
        obj_transform = self.curr_obj.transformation

        # only need to iterate over first 4 corners to draw whole thing
        for i in range(int(num_corners / 2)):
            # back of box
            back_corner_local_pos = bb_corners[i]
            back_corner_world_pos = obj_transform.transform_point(back_corner_local_pos)
            next_back_index = (i + 1) % 4
            next_back_corner_local_pos = bb_corners[next_back_index]
            next_back_corner_world_pos = obj_transform.transform_point(
                next_back_corner_local_pos
            )
            self.get_debug_line_render().draw_transformed_line(
                back_corner_world_pos,
                next_back_corner_world_pos,
                line_color,
            )
            # side edge that this corner is a part of
            front_counterpart_index = num_corners - i - 1
            front_counterpart_local_pos = bb_corners[front_counterpart_index]
            front_counterpart_world_pos = obj_transform.transform_point(
                front_counterpart_local_pos
            )
            self.get_debug_line_render().draw_transformed_line(
                back_corner_world_pos,
                front_counterpart_world_pos,
                line_color,
            )
            # front of box
            next_front_index = (front_counterpart_index - 4 - 1) % 4 + 4
            next_front_corner_local_pos = bb_corners[next_front_index]
            next_front_corner_world_pos = obj_transform.transform_point(
                next_front_corner_local_pos
            )
            self.get_debug_line_render().draw_transformed_line(
                front_counterpart_world_pos,
                next_front_corner_world_pos,
                line_color,
            )

    def draw_collision_asset_wireframe(self, sensor_uuid: str) -> None:
        """ """
        agent = self.get_agent(0)
        render_cam = agent.scene_node.node_sensor_suite.get(sensor_uuid).render_camera
        proj_mat = render_cam.projection_matrix.__matmul__(render_cam.camera_matrix)
        self.physics_debug_draw(proj_mat)

    def draw_physics(self) -> None:
        ...


class RotationAxis(Tuple, Enum):
    Y = (0.0, 1.0, 0.0)
    X = (1.0, 0.0, 0.0)


class ANSICodes(Enum):
    """
    Terminal printing ANSI color and format codes
    """

    HEADER = "\033[95m"
    BROWN = "\033[38;5;130m"
    ORANGE = "\033[38;5;202m"
    YELLOW = "\033[38;5;220m"
    PURPLE = "\033[38;5;177m"
    BRIGHT_RED = "\033[38;5;196m"
    BRIGHT_BLUE = "\033[38;5;27m"
    BRIGHT_MAGENTA = "\033[38;5;201m"
    BRIGHT_CYAN = "\033[38;5;14m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    BOLD = "\033[1m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"


class CSVWriter:
    """
    Generalized utility to write csv files
    """

    def write_file(
        headers: List[str],
        csv_rows: List[List[str]],
        file_path: str,
    ) -> None:
        """
        Write column titles and csv data into csv file with the provided
        file path.
        :param headers: List of strings that refers to csv column titles
        :param csv_rows: A List of a List of strings, where each List of strings
        is a row of the csv file, one string entry for each column
        :param file_path: absolute file path of csv file to save to
        """
        # make sure the number of columns line up
        if not len(csv_rows[0]) == len(headers):
            raise RuntimeError(
                "Number of headers does not equal number of columns in CSVWriter.write_file()."
            )

        with open(file_path, "w") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(headers)
            writer.writerows(csv_rows)


class MemoryUnitConverter:
    """
    class to convert computer memory value units, i.e.
    1,024 bytes to 1 kilobyte, or (1 << 10) bytes
    1,048,576 bytes to 1 megabyte, or (1 << 20) bytes
    1,073,741,824 bytes to 1 gigabyte, or (1 << 30) bytes
    """

    BYTES = 0
    KILOBYTES = 1
    MEGABYTES = 2
    GIGABYTES = 3

    UNIT_STRS = ["bytes", "KB", "MB", "GB"]
    UNIT_CONVERSIONS = [1, 1 << 10, 1 << 20, 1 << 30]


def print_if_logging(sim: DatasetProcessorSim, message: str = "") -> None:
    """
    Print to console if "sim.silent" is set to false in the config file
    """
    if not sim.silent:
        print(message)


def print_debug(sim: DatasetProcessorSim, message: str = "") -> None:
    """
    Print to console if "sim.debug_print" is set to true in the config file
    """
    if sim.debug_print:
        print(message)


def print_mem_usage_info(
    sim: DatasetProcessorSim,
    start_mem,
    end_mem,
    avg_ram_used_str: str,
) -> None:
    """"""
    # Print memory usage info before loading object
    text_format = ANSICodes.BRIGHT_RED.value
    print_if_logging(sim, text_format + "\nstart mem state" + section_divider)
    for key, value in start_mem.items():
        value_str = value
        if key != "percent":
            value_str = get_mem_size_str(value)
        print_if_logging(sim, text_format + f"{key} : {value_str}")

    # Print memory usage info after loading object
    print_if_logging(sim, text_format + "\nend mem state" + section_divider)
    for key, value in end_mem.items():
        value_str = value
        if key != "percent":
            value_str = get_mem_size_str(value)
        print_if_logging(sim, text_format + f"{key} : {value_str}")

    # Print difference in memory usage before and after loading object
    print_if_logging(sim, text_format + "\nchange in mem states" + section_divider)
    for (key_s, value_s), (key_e, value_e) in zip(start_mem.items(), end_mem.items()):
        value_str = value_e - value_s
        if key_s != "percent" and key_e != "percent":
            value_str = get_mem_size_str(value_e - value_s)
        print_if_logging(sim, text_format + f"{key_s} : {value_str}")

    # Print rough estimate of RAM used when loading object
    print_if_logging(
        sim,
        text_format + "\naverage RAM used" + section_divider + f"\n{avg_ram_used_str}",
    )


def create_unique_filename(
    dir_path: str, extension: str, filename_prefix: str = None
) -> str:
    """
    Create unique file name / file path based off of the current date and time.
    Also create directory in which we save the file if one doesn't already exist
    :param dir_path: Absolute file path of directory in which to create this new
    file
    :param extension: extension of file name. Of the form ".mp4", ".csv", etc
    :param filename_prefix: if you want the filename to be more descriptive,
    rather than just have the date and time. The filepath will be of the form:
    <path to dir>/<filename_prefix>__date_<year>-<month>-<day>__time_<hour>:<min>:<sec>.
    If no filename_prefix: <path to dir>/date_<year>-<month>-<day>__time_<hour>:<min>:<sec>
    """
    # Current date and time so we can make unique file names for each csv
    date_and_time = datetime.datetime.now()

    # year-month-day
    date = date_and_time.strftime("%Y-%m-%d")

    # hour:min:sec - capital H is military time, %I is standard time
    # (am/pm time format)
    time = date_and_time.strftime("%H:%M:%S")

    # make directory to store file if it doesn't exist
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)

    # adjust prefix to make sure there is a delimeter between it and the rest
    # of the file name
    if filename_prefix is None or filename_prefix == "":
        filename_prefix = ""
    else:
        filename_prefix = f"{filename_prefix}__"

    # make sure directory path and filename extension are formatted correctly
    if not dir_path.endswith("/"):
        dir_path = dir_path + "/"
    if not extension.startswith("."):
        extension = "." + extension

    # create file name
    file_path = f"{dir_path}{filename_prefix}date_{date}__time_{time}{extension}"
    return file_path


def convert_memory_units(
    size: float,
    unit_type: int = MemoryUnitConverter.KILOBYTES,
    decimal_num_round: int = 2,
) -> float:
    """
    Convert units from bytes to desired unit, then round the result
    """
    new_size = size / MemoryUnitConverter.UNIT_CONVERSIONS[unit_type]
    return round(new_size, decimal_num_round)


def get_mem_size_str(
    size: float,
    unit_type: int = MemoryUnitConverter.KILOBYTES,
) -> str:
    """
    Convert bytes to desired memory unit size, then create string
    that will be written into csv file rows. Add commas to numbers
    """
    new_size: float = convert_memory_units(size, unit_type)
    new_size_str: str = "{:,}".format(new_size)
    unit_str: str = MemoryUnitConverter.UNIT_STRS[unit_type]
    return f"{new_size_str} {unit_str}"


def get_bounding_box_corners(obj: physics.ManagedBulletRigidObject) -> List[mn.Vector3]:
    """
    Return a list of object bounding box corners in object local space.
    :param obj: a physics.ManagedBulletObject
    """
    bounding_box = obj.root_scene_node.cumulative_bb
    return [
        bounding_box.back_bottom_left,
        bounding_box.back_bottom_right,
        bounding_box.back_top_right,
        bounding_box.back_top_left,
        bounding_box.front_top_left,
        bounding_box.front_top_right,
        bounding_box.front_bottom_right,
        bounding_box.front_bottom_left,
    ]


def bounding_box_ray_prescreen(
    sim: DatasetProcessorSim,
    obj: physics.ManagedBulletRigidObject,
    support_obj_ids: Optional[List[int]] = None,
    check_all_corners: bool = False,
) -> Dict[str, Any]:
    """
    Pre-screen a potential placement by casting rays in the gravity direction from
    the object center of mass (and optionally each corner of its bounding box) checking
    for interferring objects below.
    :param sim: The Simulator instance.
    :param obj: The RigidObject instance.
    :param support_obj_ids: A list of object ids designated as valid support surfaces
    for object placement. Contact with other objects is a criteria for placement rejection.
    :param check_all_corners: Optionally cast rays from all bounding box corners instead
    of only casting a ray from the center of mass.
    """
    if support_obj_ids is None:
        # set default support surface to stage/ground mesh
        support_obj_ids = [-1]
    lowest_key_point: mn.Vector3 = None
    lowest_key_point_height = None
    highest_support_impact: mn.Vector3 = None
    highest_support_impact_height = None
    highest_support_impact_with_stage = False
    raycast_results = []
    gravity_dir = sim.get_gravity().normalized()
    object_local_to_global = obj.transformation
    bounding_box_corners = get_bounding_box_corners(obj)
    key_points = [mn.Vector3(0)] + bounding_box_corners  # [COM, c0, c1 ...]
    support_impacts: Dict[int, mn.Vector3] = {}  # indexed by keypoints
    for ix, key_point in enumerate(key_points):
        world_point = object_local_to_global.transform_point(key_point)
        # NOTE: instead of explicit Y coordinate, we project onto any gravity vector
        world_point_height = world_point.projected_onto_normalized(
            -gravity_dir
        ).length()
        if lowest_key_point is None or lowest_key_point_height > world_point_height:
            lowest_key_point = world_point
            lowest_key_point_height = world_point_height
        # cast a ray in gravity direction
        if ix == 0 or check_all_corners:
            ray = hsim.geo.Ray(world_point, gravity_dir)
            raycast_results.append(sim.cast_ray(ray))
            # classify any obstructions before hitting the support surface
            for hit in raycast_results[-1].hits:
                if hit.object_id == obj.object_id:
                    continue
                elif hit.object_id in support_obj_ids:
                    hit_point = ray.origin + ray.direction * hit.ray_distance
                    support_impacts[ix] = hit_point
                    support_impact_height = mn.math.dot(hit_point, -gravity_dir)

                    if (
                        highest_support_impact is None
                        or highest_support_impact_height < support_impact_height
                    ):
                        highest_support_impact = hit_point
                        highest_support_impact_height = support_impact_height
                        highest_support_impact_with_stage = hit.object_id == -1

                # terminates at the first non-self ray hit
                break

    # compute the relative base height of the object from its lowest bounding_box corner and COM
    base_rel_height = (
        lowest_key_point_height
        - obj.translation.projected_onto_normalized(-gravity_dir).length()
    )

    # account for the affects of stage mesh margin
    margin_offset = (
        0
        if not highest_support_impact_with_stage
        else sim.get_stage_initialization_template().margin
    )

    surface_snap_point = (
        None
        if 0 not in support_impacts
        else support_impacts[0] + gravity_dir * (base_rel_height - margin_offset)
    )

    # return list of obstructed and grounded rays, relative base height,
    # distance to first surface impact, and ray results details
    return {
        "base_rel_height": base_rel_height,
        "surface_snap_point": surface_snap_point,
        "raycast_results": raycast_results,
    }


def snap_down_object(
    sim: DatasetProcessorSim,
    obj: physics.ManagedBulletRigidObject,
    support_obj_ids: Optional[List[int]] = None,
) -> bool:
    """
    Attempt to project an object in the gravity direction onto the surface below it.
    :param sim: The Simulator instance.
    :param obj: The RigidObject instance.
    :param support_obj_ids: A list of object ids designated as valid support surfaces
    for object placement. Contact with other objects is a criteria for placement rejection.
    If none provided, default support surface is the stage/ground mesh (-1).
    :param vdb: Optionally provide a DebugVisualizer (vdb) to render debug images of each
    object's computed snap position before collision culling.
    Reject invalid placements by checking for penetration with other existing objects.
    Returns boolean success.
    If placement is successful, the object state is updated to the snapped location.
    If placement is rejected, object position is not modified and False is returned.
    To use this utility, generate an initial placement for any object above any of the
    designated support surfaces and call this function to attempt to snap it onto the
    nearest surface in the gravity direction.
    """
    cached_position = obj.translation

    if support_obj_ids is None:
        # set default support surface to stage/ground mesh
        support_obj_ids = [-1]

    bounding_box_ray_prescreen_results = bounding_box_ray_prescreen(
        sim, obj, support_obj_ids
    )

    if bounding_box_ray_prescreen_results["surface_snap_point"] is None:
        # no support under this object, return failure
        return False

    # finish up
    if bounding_box_ray_prescreen_results["surface_snap_point"] is not None:
        # accept the final location if a valid location exists
        obj.translation = bounding_box_ray_prescreen_results["surface_snap_point"]
        sim.perform_discrete_collision_detection()
        cps = sim.get_physics_contact_points()
        for cp in cps:
            if (
                cp.object_id_a == obj.object_id or cp.object_id_b == obj.object_id
            ) and (
                (cp.contact_distance < -0.01)
                or not (
                    cp.object_id_a in support_obj_ids
                    or cp.object_id_b in support_obj_ids
                )
            ):
                obj.translation = cached_position
                return False
        return True
    else:
        # no valid position found, reset and return failure
        obj.translation = cached_position
        return False


def create_video(sim: DatasetProcessorSim, video_file_dir: str) -> None:
    # construct file path and write "observations" to video file
    obj_handle = sim.curr_obj.handle.replace("_:0000", "")
    video_file_prefix = sim.sim_settings["output_paths"].get("output_file_prefix")
    video_file_prefix += f"_{obj_handle}"
    file_path = create_unique_filename(video_file_dir, ".mp4", video_file_prefix)
    vut.make_video(
        sim.observations,
        "color_sensor",
        "color",
        file_path,
        open_vid=False,
    )


def get_csv_headers(sim: DatasetProcessorSim) -> List[str]:
    """
    Collect the csv column titles we'll need given which tests we ran
    """
    headers: List[str] = sim.sim_settings["object_name"]
    data_to_collect = sim.sim_settings["data_to_collect"]
    if data_to_collect.get("memory_data"):
        headers += sim.sim_settings["memory_data_headers"]
    if data_to_collect.get("render_time_ratio"):
        headers += sim.sim_settings["render_time_headers"]
    if data_to_collect.get("physics_data"):
        headers += sim.sim_settings["physics_data_headers"]

    return headers


def create_csv_file(
    sim: DatasetProcessorSim,
    headers: List[str],
    csv_rows: List[List[str]],
    csv_dir_path: str = None,
    csv_file_prefix: str = None,
) -> None:
    """
    Set directory where our csv's will be saved, create the csv file name,
    create the column names of our csv data, then open and write the csv
    file
    :param headers: column titles of csv file
    :param csv_rows: List of Lists of strings defining asset processing results
    for each dataset object
    :param csv_dir_path: absolute path to directory where csv file will be saved
    :param csv_file_prefix: prefix we will add to beginning of the csv filename
    to specify which dataset this csv is describing
    """
    file_path = create_unique_filename(csv_dir_path, ".csv", csv_file_prefix)

    text_format = ANSICodes.PURPLE.value + ANSICodes.BOLD.value
    print_if_logging(sim, text_format + "\nWriting csv results to:" + section_divider)
    text_format = ANSICodes.PURPLE.value
    print_if_logging(sim, text_format + f"{file_path}\n")

    CSVWriter.write_file(headers, csv_rows, file_path)

    text_format = ANSICodes.PURPLE.value
    print_if_logging(sim, text_format + "CSV writing done\n")


def configure_sim(sim_settings: Dict[str, Any]):
    """
    Configure simulator while adding post configuration for the transform of
    the agent
    """
    cfg = make_cfg(sim_settings)
    sim = DatasetProcessorSim(cfg)
    sim.sim_settings = sim_settings
    sim.silent = sim_settings["silent"]
    sim.debug_print = sim_settings["debug_print"]

    default_transforms = sim_settings["default_transforms"]

    # init agent
    agent_state = hsim.AgentState()
    sim.default_agent = sim.initialize_agent(sim_settings["default_agent"], agent_state)
    sim.default_agent_pos = mn.Vector3(default_transforms.get("default_agent_pos"))
    sim.default_agent.body.object.translation = sim.default_agent_pos
    agent_rot = default_transforms.get("default_agent_rot")
    angle = agent_rot.get("angle")
    axis = mn.Vector3(agent_rot.get("axis"))

    # construct rotation as quaternion, and if axis is (0, 0, 0), that means there
    # is no rotation
    if axis.is_zero():
        sim.default_agent_rot = mn.Quaternion.identity_init()
    else:
        sim.default_agent_rot = mn.Quaternion.rotation(mn.Rad(mn.Deg(angle)), axis)
    sim.default_agent.body.object.rotation = sim.default_agent_rot

    # save default rigid object transforms
    sim.default_obj_pos = default_transforms.get("default_obj_pos")
    obj_rot = default_transforms.get("default_obj_rot")
    angle = mn.Rad(mn.Deg(obj_rot.get("angle")))
    axis = mn.Vector3(obj_rot.get("axis"))
    sim.default_obj_rot = mn.Quaternion.rotation(angle, axis)

    return sim


def update_sim_settings(
    sim_settings: Dict[str, Any], config_settings
) -> Dict[str, Any]:
    """
    Update nested sim_settings dictionary. Modifies sim_settings in place.
    """
    for key, value in config_settings.items():
        if isinstance(value, Dict) and value:
            returned = update_sim_settings(sim_settings.get(key, {}), value)
            sim_settings[key] = returned
        else:
            sim_settings[key] = config_settings[key]

    return sim_settings


def build_parser(
    parser: Optional[argparse.ArgumentParser] = None,
) -> argparse.ArgumentParser:
    """
    Parse config file argument or set default when running script for scene and
    dataset
    """
    if parser is None:
        parser = argparse.ArgumentParser(
            description="Tool to evaluate all objects in a dataset. Assesses CPU, GPU, mesh size, "
            " and other characteristics to determine if an object will be problematic when using it"
            " in a simulation",
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        )
    parser = argparse.ArgumentParser()

    # optional arguments
    parser.add_argument(
        "--config_file_path",
        default="tools/dataset_object_processor/configs/default.dataset_processor_config.json",
        type=str,
        help="config file to load"
        ' (default: "tools/dataset_object_processor/configs/default.dataset_processor_config.json")',
    )
    return parser
