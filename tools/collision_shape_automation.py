# Copyright (c) Meta Platforms, Inc. and its affiliates.
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import argparse
import math
import os
import random
import time
from typing import Any, Dict, List, Tuple

# imports from Habitat-lab
# NOTE: requires PR 1108 branch: rearrange-gen-improvements (https://github.com/facebookresearch/habitat-lab/pull/1108)
import habitat.datasets.rearrange.samplers.receptacle as hab_receptacle
import habitat.sims.habitat_simulator.debug_visualizer as hab_debug_vis
import magnum as mn
import numpy as np
from habitat.sims.habitat_simulator.sim_utilities import snap_down

import habitat_sim
from habitat_sim.utils.settings import default_sim_settings, make_cfg

# object samples:
# chair - good approximation: 0a5e809804911e71de6a4ef89f2c8fef5b9291b3.glb
# shelves - bad approximation: d1d1e0cdaba797ee70882e63f66055675c3f1e7f.glb

# 71 equidistant points on a unit hemisphere generated from icosphere subdivision
# Sphere center is (0,0,0) and no points lie on x,z plane
# used for hemisphere raycasting from Receptacle points
icosphere_points_subdiv_3 = [
    mn.Vector3(-0.276388, 0.447220, -0.850649),
    mn.Vector3(-0.483971, 0.502302, -0.716565),
    mn.Vector3(-0.232822, 0.657519, -0.716563),
    mn.Vector3(0.723607, 0.447220, -0.525725),
    mn.Vector3(0.531941, 0.502302, -0.681712),
    mn.Vector3(0.609547, 0.657519, -0.442856),
    mn.Vector3(0.723607, 0.447220, 0.525725),
    mn.Vector3(0.812729, 0.502301, 0.295238),
    mn.Vector3(0.609547, 0.657519, 0.442856),
    mn.Vector3(-0.276388, 0.447220, 0.850649),
    mn.Vector3(-0.029639, 0.502302, 0.864184),
    mn.Vector3(-0.232822, 0.657519, 0.716563),
    mn.Vector3(-0.894426, 0.447216, 0.000000),
    mn.Vector3(-0.831051, 0.502299, 0.238853),
    mn.Vector3(-0.753442, 0.657515, 0.000000),
    mn.Vector3(-0.251147, 0.967949, 0.000000),
    mn.Vector3(-0.077607, 0.967950, 0.238853),
    mn.Vector3(0.000000, 1.000000, 0.000000),
    mn.Vector3(-0.525730, 0.850652, 0.000000),
    mn.Vector3(-0.361800, 0.894429, 0.262863),
    mn.Vector3(-0.638194, 0.723610, 0.262864),
    mn.Vector3(-0.162456, 0.850654, 0.499995),
    mn.Vector3(-0.447209, 0.723612, 0.525728),
    mn.Vector3(-0.688189, 0.525736, 0.499997),
    mn.Vector3(-0.483971, 0.502302, 0.716565),
    mn.Vector3(0.203181, 0.967950, 0.147618),
    mn.Vector3(0.138197, 0.894430, 0.425319),
    mn.Vector3(0.052790, 0.723612, 0.688185),
    mn.Vector3(0.425323, 0.850654, 0.309011),
    mn.Vector3(0.361804, 0.723612, 0.587778),
    mn.Vector3(0.262869, 0.525738, 0.809012),
    mn.Vector3(0.531941, 0.502302, 0.681712),
    mn.Vector3(0.203181, 0.967950, -0.147618),
    mn.Vector3(0.447210, 0.894429, 0.000000),
    mn.Vector3(0.670817, 0.723611, 0.162457),
    mn.Vector3(0.425323, 0.850654, -0.309011),
    mn.Vector3(0.670817, 0.723611, -0.162457),
    mn.Vector3(0.850648, 0.525736, 0.000000),
    mn.Vector3(0.812729, 0.502301, -0.295238),
    mn.Vector3(-0.077607, 0.967950, -0.238853),
    mn.Vector3(0.138197, 0.894430, -0.425319),
    mn.Vector3(0.361804, 0.723612, -0.587778),
    mn.Vector3(-0.162456, 0.850654, -0.499995),
    mn.Vector3(0.052790, 0.723612, -0.688185),
    mn.Vector3(0.262869, 0.525738, -0.809012),
    mn.Vector3(-0.029639, 0.502302, -0.864184),
    mn.Vector3(-0.361800, 0.894429, -0.262863),
    mn.Vector3(-0.447209, 0.723612, -0.525728),
    mn.Vector3(-0.638194, 0.723610, -0.262864),
    mn.Vector3(-0.688189, 0.525736, -0.499997),
    mn.Vector3(-0.831051, 0.502299, -0.238853),
    mn.Vector3(-0.956626, 0.251149, 0.147618),
    mn.Vector3(-0.861804, 0.276396, 0.425322),
    mn.Vector3(-0.670821, 0.276397, 0.688189),
    mn.Vector3(-0.436007, 0.251152, 0.864188),
    mn.Vector3(-0.155215, 0.251152, 0.955422),
    mn.Vector3(0.138199, 0.276397, 0.951055),
    mn.Vector3(0.447215, 0.276397, 0.850649),
    mn.Vector3(0.687159, 0.251152, 0.681715),
    mn.Vector3(0.860698, 0.251151, 0.442858),
    mn.Vector3(0.947213, 0.276396, 0.162458),
    mn.Vector3(0.947213, 0.276397, -0.162458),
    mn.Vector3(0.860698, 0.251151, -0.442858),
    mn.Vector3(0.687159, 0.251152, -0.681715),
    mn.Vector3(0.447216, 0.276397, -0.850648),
    mn.Vector3(0.138199, 0.276397, -0.951055),
    mn.Vector3(-0.155215, 0.251152, -0.955422),
    mn.Vector3(-0.436007, 0.251152, -0.864188),
    mn.Vector3(-0.670820, 0.276396, -0.688190),
    mn.Vector3(-0.861804, 0.276394, -0.425323),
    mn.Vector3(-0.956626, 0.251149, -0.147618),
]


def get_scaled_hemisphere_vectors(scale: float):
    return [v * scale for v in icosphere_points_subdiv_3]


# =======================================================================
# Range3D surface sampling utils


def compute_area_weights_for_range3d_faces(range3d: mn.Range3D):
    """
    Compute a set of area weights from a Range3D.
    """

    face_areas = [
        range3d.size_x() * range3d.size_y(),  # front/back
        range3d.size_x() * range3d.size_z(),  # top/bottom
        range3d.size_y() * range3d.size_z(),  # sides
    ]
    area_accumulator = []
    for ix in range(6):
        area_ix = ix % 3
        if ix == 0:
            area_accumulator.append(face_areas[area_ix])
        else:
            area_accumulator.append(face_areas[area_ix] + area_accumulator[-1])

    normalized_area_accumulator = [x / area_accumulator[-1] for x in area_accumulator]

    return normalized_area_accumulator


def get_range3d_sample_planes(range3d: mn.Range3D):
    """
    Get origin and basis vectors for each face's sample planes.
    """
    # For each face a starting point and two edge vectors (un-normalized)
    face_info: List[Tuple[mn.Vector3, mn.Vector3, mn.Vector3]] = [
        (
            range3d.front_bottom_left,
            mn.Vector3.x_axis(range3d.size_x()),
            mn.Vector3.y_axis(range3d.size_y()),
        ),  # front
        (
            range3d.back_top_left,
            mn.Vector3.x_axis(range3d.size_x()),
            mn.Vector3.z_axis(range3d.size_z()),
        ),  # top
        (
            range3d.back_bottom_left,
            mn.Vector3.y_axis(range3d.size_y()),
            mn.Vector3.z_axis(range3d.size_z()),
        ),  # left
        (
            range3d.back_bottom_left,
            mn.Vector3.x_axis(range3d.size_x()),
            mn.Vector3.y_axis(range3d.size_y()),
        ),  # back
        (
            range3d.back_bottom_left,
            mn.Vector3.x_axis(range3d.size_x()),
            mn.Vector3.z_axis(range3d.size_z()),
        ),  # bottom
        (
            range3d.back_bottom_right,
            mn.Vector3.y_axis(range3d.size_y()),
            mn.Vector3.z_axis(range3d.size_z()),
        ),  # right
    ]
    return face_info


def sample_jittered_points_from_range3d(range3d: mn.Range3D, num_points: int = 100):
    """
    Use jittered sampling to compute a more uniformly distributed set of random points.
    """
    normalized_area_accumulator = compute_area_weights_for_range3d_faces(range3d)
    normalized_areas = []
    for vix in range(len(normalized_area_accumulator)):
        if vix == 0:
            normalized_areas.append(normalized_area_accumulator[vix])
        else:
            normalized_areas.append(
                normalized_area_accumulator[vix] - normalized_area_accumulator[vix - 1]
            )

    # get number of points per face based on area
    # NOTE: rounded up, so may be slightly more points than requested.
    points_per_face = [max(1, math.ceil(x * num_points)) for x in normalized_areas]

    # get face plane basis
    face_info = get_range3d_sample_planes(range3d)

    # one internal list of each face of the box:
    samples = []
    for _ in range(6):
        samples.append([])

    real_total_points = 0
    # print("Sampling Stats: ")
    # for each face, jittered sample of total area:
    for face_ix, f in enumerate(face_info):
        # get ratio of width/height in local space to plan jittering
        aspect_ratio = f[1].length() / f[2].length()
        num_wide = max(1, int(math.sqrt(aspect_ratio * points_per_face[face_ix])))
        num_high = max(1, int((points_per_face[face_ix] + num_wide - 1) / num_wide))
        total_points = num_wide * num_high
        real_total_points += total_points
        # print(f"    f_{face_ix}: ")
        # print(f"        points_per_face = {points_per_face[face_ix]}")
        # print(f"        aspect_ratio = {aspect_ratio}")
        # print(f"        num_wide = {num_wide}")
        # print(f"        num_high = {num_high}")
        # print(f"        total_points = {total_points}")

        # get jittered cell sizes
        dx = f[1] / num_wide
        dy = f[2] / num_high
        for x in range(num_wide):
            for y in range(num_high):
                # get cell origin
                org = f[0] + x * dx + y * dy
                # point is randomly placed in the cell
                point = org + random.random() * dx + random.random() * dy
                samples[face_ix].append(point)
    # print(f"        real_total_points = {real_total_points}")

    return samples


def sample_points_from_range3d(
    range3d: mn.Range3D, num_points: int = 100
) -> List[List[mn.Vector3]]:
    """
    Sample 'num_points' from the surface of a box defeined by 'range3d'.
    """

    # -----------------------------------------
    # area weighted face sampling
    normalized_area_accumulator = compute_area_weights_for_range3d_faces(range3d)

    def sample_face() -> int:
        """
        Weighted sampling of a face from the area accumulator.
        """
        rand = random.random()
        for ix in range(6):
            if normalized_area_accumulator[ix] > rand:
                return ix
        raise (AssertionError, "Should not reach here.")

    # -----------------------------------------

    face_info = get_range3d_sample_planes(range3d)

    # one internal list of each face of the box:
    samples = []
    for _ in range(6):
        samples.append([])

    # sample points for random faces
    for _ in range(num_points):
        face_ix = sample_face()
        f = face_info[face_ix]
        point = f[0] + random.random() * f[1] + random.random() * f[2]
        samples[face_ix].append(point)

    return samples


# End - Range3D surface sampling utils
# =======================================================================


def sample_points_from_sphere(
    center: mn.Vector3,
    radius: float,
    num_points: int = 100,
) -> List[List[mn.Vector3]]:
    """
    Sample num_points from a sphere defined by center and radius.
    Return all points in two identical lists to indicate pairwise raycasting.
    :param center: sphere center position
    :param radius: sphere radius
    :param num_points: number of points to sample
    """
    samples = []

    # sample points
    while len(samples) < num_points:
        # rejection sample unit sphere from volume
        rand_point = np.random.random(3) * 2.0 - np.ones(1)
        vec_len = np.linalg.norm(rand_point)
        if vec_len < 1.0:
            # inside the sphere, so project to the surface
            samples.append(mn.Vector3(rand_point / vec_len))
        # else outside the sphere, so rejected

    # move from unit sphere to input sphere
    samples = [x * radius + center for x in samples]

    # collect into pairwise datastructure
    samples = [samples, samples]

    return samples


def receptacle_density_sample(
    sim: habitat_sim.simulator.Simulator,
    receptacle: hab_receptacle.TriangleMeshReceptacle,
    target_radius: float = 0.04,
    max_points: int = 100,
    min_points: int = 5,
    max_tries: int = 200,
):
    target_point_area = math.pi * target_radius**2
    expected_points = receptacle.total_area / target_point_area

    # if necessary, compute new target_radius to best cover the area
    if expected_points > max_points or expected_points < min_points:
        expected_points = max(min_points, min(max_points, expected_points))
        target_radius = math.sqrt(receptacle.total_area / (expected_points * math.pi))

    # print(f"receptacle_density_sample(`{receptacle.name}`): area={receptacle.total_area}, r={target_radius}, num_p={expected_points}")

    sampled_points = []
    num_tries = 0
    min_dist = target_radius * 2
    while len(sampled_points) < expected_points and num_tries < max_tries:
        sample_point = receptacle.sample_uniform_global(sim, sample_region_scale=1.0)
        success = True
        for existing_point in sampled_points:
            if (sample_point - existing_point).length() < min_dist:
                num_tries += 1
                success = False
                break
        if success:
            # print(f"        success {sample_point} in {num_tries} tries")

            # if no rejection, add the point
            sampled_points.append(sample_point)
            num_tries = 0

    # print(f"    found {len(sampled_points)}/{expected_points} points.")

    return sampled_points, target_radius


def run_pairwise_raycasts(
    points: List[List[mn.Vector3]],
    sim: habitat_sim.Simulator,
    min_dist: float = 0.05,
    discard_invalid_results: bool = True,
) -> List[habitat_sim.physics.RaycastResults]:
    """
    Raycast between each pair of points from different surfaces.
    :param min_dist: The minimum ray distance to allow. Cull all candidate pairs closer than this distance.
    :param discard_invalid_results: If true, discard ray hit distances > 1
    """
    ray_max_local_dist = 100.0  # default
    if discard_invalid_results:
        # disallow contacts outside of the bounding volume (shouldn't happen anyway...)
        ray_max_local_dist = 1.0
    all_raycast_results: List[habitat_sim.physics.RaycastResults] = []
    print("Rays detected with invalid hit distance: ")
    for fix0 in range(len(points)):
        for fix1 in range(len(points)):
            if fix0 != fix1:  # no pairs on the same face
                for p0 in points[fix0]:
                    for p1 in points[fix1]:
                        if (p0 - p1).length() > min_dist:
                            # this is a valid pair of points
                            ray = habitat_sim.geo.Ray(p0, p1 - p0)  # origin, direction
                            # raycast
                            all_raycast_results.append(
                                sim.cast_ray(ray=ray, max_distance=ray_max_local_dist)
                            )
                            # reverse direction as separate entry (because exiting a convex does not generate a hit record)
                            ray2 = habitat_sim.geo.Ray(p1, p0 - p1)  # origin, direction
                            # raycast
                            all_raycast_results.append(
                                sim.cast_ray(ray=ray2, max_distance=ray_max_local_dist)
                            )

                            # prints invalid rays if not discarded by discard_invalid_results==True
                            for ix in [-1, -2]:
                                if all_raycast_results[ix].has_hits() and (
                                    all_raycast_results[ix].hits[0].ray_distance > 1
                                    or all_raycast_results[ix].hits[0].ray_distance < 0
                                ):
                                    print(
                                        f"     distance={all_raycast_results[ix].hits[0].ray_distance}"
                                    )

    return all_raycast_results


def debug_draw_raycast_results(
    sim, ground_truth_results, proxy_results, subsample_number: int = 100, seed=0
) -> None:
    """
    Render debug lines for a subset of raycast results, randomly subsampled for efficiency.
    """
    random.seed(seed)
    red = mn.Color4.red()
    yellow = mn.Color4.yellow()
    blue = mn.Color4.blue()
    grey = mn.Color4(mn.Vector3(0.6), 1.0)
    for _ in range(subsample_number):
        result_ix = random.randint(0, len(ground_truth_results) - 1)
        ray = ground_truth_results[result_ix].ray
        gt_results = ground_truth_results[result_ix]
        pr_results = proxy_results[result_ix]

        if gt_results.has_hits() or pr_results.has_hits():
            # some logic for line colors
            first_hit_dist = 0
            # pairs of distances for overshooting the ground truth and undershooting the ground truth
            overshoot_dists = []
            undershoot_dists = []

            # draw first hits for gt and proxy
            if gt_results.has_hits():
                sim.get_debug_line_render().draw_circle(
                    translation=ray.origin
                    + ray.direction * gt_results.hits[0].ray_distance,
                    radius=0.005,
                    color=blue,
                    normal=gt_results.hits[0].normal,
                )
            if pr_results.has_hits():
                sim.get_debug_line_render().draw_circle(
                    translation=ray.origin
                    + ray.direction * pr_results.hits[0].ray_distance,
                    radius=0.005,
                    color=yellow,
                    normal=pr_results.hits[0].normal,
                )

            if not gt_results.has_hits():
                first_hit_dist = pr_results.hits[0].ray_distance
                overshoot_dists.append((first_hit_dist, 1.0))
            elif not pr_results.has_hits():
                first_hit_dist = gt_results.hits[0].ray_distance
                undershoot_dists.append((first_hit_dist, 1.0))
            else:
                # both have hits
                first_hit_dist = min(
                    gt_results.hits[0].ray_distance, pr_results.hits[0].ray_distance
                )

                # compute overshoots and undershoots for first hit:
                if gt_results.hits[0].ray_distance < pr_results.hits[0].ray_distance:
                    # undershoot
                    undershoot_dists.append(
                        (
                            gt_results.hits[0].ray_distance,
                            pr_results.hits[0].ray_distance,
                        )
                    )
                else:
                    # overshoot
                    overshoot_dists.append(
                        (
                            gt_results.hits[0].ray_distance,
                            pr_results.hits[0].ray_distance,
                        )
                    )

            # draw blue lines for overlapping distances
            sim.get_debug_line_render().draw_transformed_line(
                ray.origin, ray.origin + ray.direction * first_hit_dist, blue
            )

            # draw red lines for overshoots (proxy is outside the ground truth)
            for d0, d1 in overshoot_dists:
                sim.get_debug_line_render().draw_transformed_line(
                    ray.origin + ray.direction * d0,
                    ray.origin + ray.direction * d1,
                    red,
                )

            # draw yellow lines for undershoots (proxy is inside the ground truth)
            for d0, d1 in undershoot_dists:
                sim.get_debug_line_render().draw_transformed_line(
                    ray.origin + ray.direction * d0,
                    ray.origin + ray.direction * d1,
                    yellow,
                )

        else:
            # no hits, grey line
            sim.get_debug_line_render().draw_transformed_line(
                ray.origin, ray.origin + ray.direction, grey
            )


def get_raycast_results_cumulative_error_metric(
    ground_truth_results, proxy_results
) -> float:
    """
    Generates a scalar error metric from raycast results normalized to [0,1].

    absolute_error = sum(abs(gt_1st_hit_dist-pr_1st_hit_dist))

    To normalize error:
        0 corresponds to gt distances (absolute_error == 0)
        1 corresponds to max error. For each ray, max error is max(gt_1st_hit_dist, ray_length-gt_1st_hit_dist).
            max_error = sum(max(gt_1st_hit_dist, ray_length-gt_1st_hit_dist))
    normalized_error = error/max_error
    """
    assert len(ground_truth_results) == len(
        proxy_results
    ), "raycast results must be equivalent."

    max_error = 0
    absolute_error = 0
    for r_ix in range(len(ground_truth_results)):
        ray = ground_truth_results[r_ix].ray
        ray_len = ray.direction.length()
        local_max_error = ray_len
        gt_dist = ray_len
        if ground_truth_results[r_ix].has_hits():
            gt_dist = ground_truth_results[r_ix].hits[0].ray_distance * ray_len
            local_max_error = max(gt_dist, ray_len - gt_dist)
        max_error += local_max_error
        local_proxy_dist = ray_len
        if proxy_results[r_ix].has_hits():
            local_proxy_dist = proxy_results[r_ix].hits[0].ray_distance * ray_len
        local_absolute_error = abs(local_proxy_dist - gt_dist)
        absolute_error += local_absolute_error

    normalized_error = absolute_error / max_error
    return normalized_error


def evaluate_collision_shape(
    object_handle: str,
    sim_settings: Dict[str, Any],
    sample_shape="sphere",
    mm=None,
    num_point_samples=100,
) -> None:
    """
    Runs in-engine evaluation of collision shape accuracy for a single object.
    Uses a raycast from a bounding shape to approximate surface error between a proxy shape and ground truth (the render shape).
    Returns:
      ground_truth and proxy raw raycast results,
      the object's template handle,
      all test points used for the raycast,
      scalar error metrics
    1. initializes a simulator with the object render shape as a stage collision mesh.
    2. uses the scene bouding box to sample points on a configured bounding shape (e.g. inflated AABB or sphere).
    3. raycasts between sampled point pairs on both ground truth and collision proxy shapes to heuristicall measure error.
    4. computes scalar error metrics

    :param object_handle: The object to evaluate.
    :param sim_settings: Any simulator settings for initialization (should be physics enabled and point to correct dataset).
    :param sample_shape: The desired bounding shape for raycast: "sphere" or "aabb", "jittered_aabb".
    :param mm: A pre-configured MetadataMediator may be provided to reduce initialization time. Should have the correct dataset already configured.
    """
    profile_metrics = {}
    start_time = time.time()
    check_time = time.time()
    cfg = make_cfg(sim_settings)
    if mm is not None:
        cfg.metadata_mediator = mm
    with habitat_sim.Simulator(cfg) as sim:
        profile_metrics["init0"] = time.time() - check_time
        check_time = time.time()
        # evaluate the collision shape defined in an object's template
        # 1. get the template from MM
        matching_templates = sim.get_object_template_manager().get_template_handles(
            object_handle
        )
        assert (
            len(matching_templates) == 1
        ), f"Multiple or no template matches for handle '{object_handle}': ({matching_templates})"
        obj_template_handle = matching_templates[0]
        obj_template = sim.get_object_template_manager().get_template_by_handle(
            obj_template_handle
        )
        obj_template.compute_COM_from_shape = False
        obj_template.com = mn.Vector3(0)
        # obj_template.bounding_box_collisions = True
        # obj_template.is_collidable = False
        sim.get_object_template_manager().register_template(obj_template)
        # 2. Setup a stage from the object's render mesh
        stm = sim.get_stage_template_manager()
        stage_template_name = "obj_as_stage_template"
        new_stage_template = stm.create_new_template(handle=stage_template_name)
        new_stage_template.render_asset_handle = obj_template.render_asset_handle
        stm.register_template(
            template=new_stage_template, specified_handle=stage_template_name
        )
        # 3. Initialize the simulator for the stage
        new_settings = sim_settings.copy()
        new_settings["scene"] = stage_template_name
        new_config = make_cfg(new_settings)
        sim.reconfigure(new_config)
        profile_metrics["init_stage"] = time.time() - check_time
        check_time = time.time()

        # 4. compute initial metric baselines
        scene_bb = sim.get_active_scene_graph().get_root_node().cumulative_bb
        inflated_scene_bb = scene_bb.scaled(mn.Vector3(1.25))
        inflated_scene_bb = mn.Range3D.from_center(
            scene_bb.center(), inflated_scene_bb.size() / 2.0
        )
        test_points = None
        if sample_shape == "aabb":
            # bounding box sample
            test_points = sample_points_from_range3d(
                range3d=inflated_scene_bb, num_points=num_point_samples
            )
        elif sample_shape == "jittered_aabb":
            # bounding box sample
            test_points = sample_jittered_points_from_range3d(
                range3d=inflated_scene_bb, num_points=num_point_samples
            )
        elif sample_shape == "sphere":
            # bounding sphere sample
            half_diagonal = (scene_bb.max - scene_bb.min).length() / 2.0
            test_points = sample_points_from_sphere(
                center=inflated_scene_bb.center(),
                radius=half_diagonal,
                num_points=num_point_samples,
            )
        else:
            raise NotImplementedError(
                f"sample_shape == `{sample_shape}` is not implemented. Use `sphere` or `aabb`."
            )
        profile_metrics["sample_points"] = time.time() - check_time
        check_time = time.time()

        print("GT raycast:")
        gt_raycast_results = run_pairwise_raycasts(test_points, sim)
        profile_metrics["raycast_stage"] = time.time() - check_time
        check_time = time.time()

        # 5. load the object with proxy (in NONE stage)
        new_settings = sim_settings.copy()
        new_config = make_cfg(new_settings)
        sim.reconfigure(new_config)
        obj = sim.get_rigid_object_manager().add_object_by_template_handle(
            obj_template_handle
        )
        obj.translation = obj.com
        profile_metrics["init_object"] = time.time() - check_time
        check_time = time.time()

        # 6. compute the metric for proxy object
        print("PR raycast:")
        pr_raycast_results = run_pairwise_raycasts(test_points, sim)
        profile_metrics["raycast_object"] = time.time() - check_time
        check_time = time.time()

        # 7. compare metrics
        normalized_error = get_raycast_results_cumulative_error_metric(
            gt_raycast_results, pr_raycast_results
        )
        profile_metrics["compute_metrics"] = time.time() - check_time
        check_time = time.time()
        profile_metrics["total"] = time.time() - start_time

        return (
            gt_raycast_results,
            pr_raycast_results,
            obj_template_handle,
            test_points,
            normalized_error,
            profile_metrics,
        )


# ===================================================================
# CollisionProxyOptimizer class provides a stateful API for
# configurable evaluation and optimization of collision proxy shapes.
# ===================================================================


class CollisionProxyOptimizer:
    """
    Stateful control flow for using Habitat-sim to evaluate and optimize collision proxy shapes.
    """

    def __init__(self, sim_settings: Dict[str, Any], output_directory="") -> None:
        # load the dataset into a persistent, shared MetadataMediator instance.
        self.mm = habitat_sim.metadata.MetadataMediator()
        self.mm.active_dataset = sim_settings["scene_dataset_config_file"]
        self.sim_settings = sim_settings.copy()

        # path to the desired output directory for images/csv
        self.output_directory = output_directory
        os.makedirs(self.output_directory, exist_ok=True)

        # if true, render and save debug images in self.output_directory
        self.generate_debug_images = False

        # option to use Receptacle annotations to compute an additional accuracy metric
        self.compute_receptacle_useability_metrics = True
        # add a vertical epsilon offset to the receptacle points for analysis. This is added directly to the sampled points.
        self.rec_point_vertical_offset = 0.02

        # cache of test points, rays, distances, etc... for use by active processes
        # NOTE: entries created by `setup_obj_gt` and cleaned by `clean_obj_gt` for memory efficiency.
        self.gt_data: Dict[str, Dict[str, Any]] = {}

        # cache global results to be written to csv.
        self.results: Dict[str, Dict[str, Any]] = {}

    def get_cfg_with_mm(
        self, scene: str = "NONE"
    ) -> habitat_sim.simulator.Configuration:
        """
        Get a Configuration object for initializing habitat_sim Simulator object with the correct dataset and MetadataMediator passed along.

        :param scene: The desired scene entry, defaulting to the empty NONE scene.
        """
        sim_settings = self.sim_settings.copy()
        sim_settings["scene_dataset_config_file"] = self.mm.active_dataset
        sim_settings["scene"] = scene
        cfg = make_cfg(sim_settings)
        cfg.metadata_mediator = self.mm
        return cfg

    def setup_obj_gt(
        self,
        obj_handle: str,
        sample_shape: str = "jittered_aabb",
        num_point_samples=100,
    ) -> None:
        """
        Prepare the ground truth and sample point sets for an object.
        """
        assert (
            obj_handle not in self.gt_data
        ), f"`{obj_handle}` already setup in gt_data: {self.gt_data.keys()}"

        # find object
        otm = self.mm.object_template_manager
        obj_template = otm.get_template_by_handle(obj_handle)
        assert obj_template is not None, f"Could not find object handle `{obj_handle}`"

        self.gt_data[obj_handle] = {}
        self.gt_data[obj_handle]["next_proxy_id"] = 0

        # correct now for any COM automation
        obj_template.compute_COM_from_shape = False
        obj_template.com = mn.Vector3(0)
        otm.register_template(obj_template)

        if self.compute_receptacle_useability_metrics or self.generate_debug_images:
            # pre-process the ground truth object and receptacles
            rec_vertical_offset = mn.Vector3(0, self.rec_point_vertical_offset, 0)
            cfg = self.get_cfg_with_mm()
            with habitat_sim.Simulator(cfg) as sim:
                # load the gt object
                rom = sim.get_rigid_object_manager()
                obj = rom.add_object_by_template_handle(obj_handle)
                assert obj.is_alive, "Object was not added correctly."

                if self.compute_receptacle_useability_metrics:
                    # get receptacles defined for the object:
                    source_template_file = obj.creation_attributes.file_directory
                    user_attr = obj.user_attributes
                    obj_receptacles = hab_receptacle.parse_receptacles_from_user_config(
                        user_attr,
                        parent_object_handle=obj.handle,
                        parent_template_directory=source_template_file,
                    )

                    # sample test points on the receptacles
                    self.gt_data[obj_handle]["receptacles"] = {}
                    for receptacle in obj_receptacles:
                        if type(receptacle) == hab_receptacle.TriangleMeshReceptacle:
                            rec_test_points = []
                            t_radius = 0.01
                            # adaptive density sample:
                            rec_test_points, t_radius = receptacle_density_sample(
                                sim, receptacle
                            )
                            # add the vertical offset
                            rec_test_points = [
                                p + rec_vertical_offset for p in rec_test_points
                            ]

                            # random sample:
                            # for _ in range(num_point_samples):
                            #    rec_test_points.append(
                            #        receptacle.sample_uniform_global(
                            #            sim, sample_region_scale=1.0
                            #        )
                            #    )
                            self.gt_data[obj_handle]["receptacles"][receptacle.name] = {
                                "sample_points": rec_test_points
                            }
                            if self.generate_debug_images:
                                debug_lines = []
                                assert (
                                    len(receptacle.mesh_data[1]) % 3 == 0
                                ), "must be triangles"
                                for face in range(
                                    int(len(receptacle.mesh_data[1]) / 3)
                                ):
                                    verts = receptacle.get_face_verts(f_ix=face)
                                    for edge in range(3):
                                        debug_lines.append(
                                            (
                                                [verts[edge], verts[(edge + 1) % 3]],
                                                mn.Color4.green(),
                                            )
                                        )
                                debug_circles = []
                                for p in rec_test_points:
                                    debug_circles.append(
                                        (
                                            (
                                                p,  # center
                                                t_radius,  # radius
                                                mn.Vector3(0, 1, 0),  # normal
                                                mn.Color4.red(),  # color
                                            )
                                        )
                                    )
                                # use DebugVisualizer to get 6-axis view of the object
                                dvb = hab_debug_vis.DebugVisualizer(
                                    sim=sim,
                                    output_path=self.output_directory,
                                    default_sensor_uuid="color_sensor",
                                )
                                dvb.peek_rigid_object(
                                    obj,
                                    peek_all_axis=True,
                                    additional_savefile_prefix=f"{receptacle.name}_",
                                    debug_lines=debug_lines,
                                    debug_circles=debug_circles,
                                )

                if self.generate_debug_images:
                    # use DebugVisualizer to get 6-axis view of the object
                    dvb = hab_debug_vis.DebugVisualizer(
                        sim=sim,
                        output_path=self.output_directory,
                        default_sensor_uuid="color_sensor",
                    )
                    dvb.peek_rigid_object(
                        obj, peek_all_axis=True, additional_savefile_prefix="gt_"
                    )

        # load a simulator instance with this object as the stage
        stm = self.mm.stage_template_manager
        stage_template_name = obj_handle + "_as_stage"
        self.gt_data[obj_handle]["stage_template_name"] = stage_template_name
        new_stage_template = stm.create_new_template(handle=stage_template_name)
        new_stage_template.render_asset_handle = obj_template.render_asset_handle
        stm.register_template(
            template=new_stage_template, specified_handle=stage_template_name
        )
        cfg = self.get_cfg_with_mm(scene=stage_template_name)
        with habitat_sim.Simulator(cfg) as sim:
            # get test points from bounding box info:
            scene_bb = sim.get_active_scene_graph().get_root_node().cumulative_bb
            inflated_scene_bb = scene_bb.scaled(mn.Vector3(1.25))
            inflated_scene_bb = mn.Range3D.from_center(
                scene_bb.center(), inflated_scene_bb.size() / 2.0
            )
            # NOTE: to save the referenced Range3D object, we need to deep or Magnum will destroy the underlying C++ objects.
            self.gt_data[obj_handle]["scene_bb"] = mn.Range3D(
                scene_bb.min, scene_bb.max
            )
            self.gt_data[obj_handle]["inflated_scene_bb"] = inflated_scene_bb
            test_points = None
            if sample_shape == "aabb":
                # bounding box sample
                test_points = sample_points_from_range3d(
                    range3d=inflated_scene_bb, num_points=num_point_samples
                )
            elif sample_shape == "jittered_aabb":
                # bounding box sample
                test_points = sample_jittered_points_from_range3d(
                    range3d=inflated_scene_bb, num_points=num_point_samples
                )
            elif sample_shape == "sphere":
                # bounding sphere sample
                half_diagonal = (scene_bb.max - scene_bb.min).length() / 2.0
                test_points = sample_points_from_sphere(
                    center=inflated_scene_bb.center(),
                    radius=half_diagonal,
                    num_points=num_point_samples,
                )
            else:
                raise NotImplementedError(
                    f"sample_shape == `{sample_shape}` is not implemented. Use `sphere` or `aabb`."
                )
            self.gt_data[obj_handle]["test_points"] = test_points

            # compute and cache "ground truth" raycast on object as stage
            gt_raycast_results = run_pairwise_raycasts(test_points, sim)
            self.gt_data[obj_handle]["raycasts"] = {
                "gt": {"results": gt_raycast_results}
            }

    def clean_obj_gt(self, obj_handle: str) -> None:
        """
        Cleans the global object cache to better manage process memory.
        Call this to clean-up after global data are written and detailed sample data are no longer necessary.
        """
        assert (
            obj_handle in self.gt_data
        ), f"`{obj_handle}` does not have any entry in gt_data: {self.gt_data.keys()}. Call to `setup_obj_gt(obj_handle)` required."
        self.gt_data.pop(obj_handle)

    def compute_baseline_metrics(self, obj_handle: str) -> None:
        """
        Computes 2 baselines for the evaluation metric and caches the results:
        1. No collision object
        2. AABB collision object
        """
        assert (
            obj_handle in self.gt_data
        ), f"`{obj_handle}` does not have any entry in gt_data: {self.gt_data.keys()}. Call to `setup_obj_gt(obj_handle)` required."

        # start with empty scene
        cfg = self.get_cfg_with_mm()
        with habitat_sim.Simulator(cfg) as sim:
            empty_raycast_results = run_pairwise_raycasts(
                self.gt_data[obj_handle]["test_points"], sim
            )
            self.gt_data[obj_handle]["raycasts"]["empty"] = {
                "results": empty_raycast_results
            }

        cfg = self.get_cfg_with_mm()
        with habitat_sim.Simulator(cfg) as sim:
            # modify the template
            obj_template = sim.get_object_template_manager().get_template_by_handle(
                obj_handle
            )
            assert (
                obj_template is not None
            ), f"Could not find object handle `{obj_handle}`"
            # bounding box as collision object
            obj_template.bounding_box_collisions = True
            sim.get_object_template_manager().register_template(obj_template)

            # load the object
            sim.get_rigid_object_manager().add_object_by_template_handle(obj_handle)

            # run evaluation
            bb_raycast_results = run_pairwise_raycasts(
                self.gt_data[obj_handle]["test_points"], sim
            )
            self.gt_data[obj_handle]["raycasts"]["bb"] = {"results": bb_raycast_results}

            # un-modify the template
            obj_template.bounding_box_collisions = False
            sim.get_object_template_manager().register_template(obj_template)

    def compute_proxy_metrics(self, obj_handle: str) -> None:
        """
        Computes the evaluation metric on the currently configred proxy shape and caches the results.
        """
        assert (
            obj_handle in self.gt_data
        ), f"`{obj_handle}` does not have any entry in gt_data: {self.gt_data.keys()}. Call to `setup_obj_gt(obj_handle)` required."

        # when evaluating multiple proxy shapes, need unique ids:
        pr_id = f"pr{self.gt_data[obj_handle]['next_proxy_id']}"
        self.gt_data[obj_handle]["next_proxy_id"] += 1

        # start with empty scene
        cfg = self.get_cfg_with_mm()
        with habitat_sim.Simulator(cfg) as sim:
            # modify the template to render collision object
            otm = self.mm.object_template_manager
            obj_template = otm.get_template_by_handle(obj_handle)
            render_asset = obj_template.render_asset_handle
            obj_template.render_asset_handle = obj_template.collision_asset_handle
            otm.register_template(obj_template)

            # load the object
            obj = sim.get_rigid_object_manager().add_object_by_template_handle(
                obj_handle
            )
            assert obj.is_alive, "Object was not added correctly."

            # check that collision shape bounding box is similar
            col_bb = obj.root_scene_node.cumulative_bb
            assert self.gt_data[obj_handle]["inflated_scene_bb"].contains(
                col_bb.min
            ) and self.gt_data[obj_handle]["inflated_scene_bb"].contains(
                col_bb.max
            ), f"Inflated bounding box does not contain the collision shape. (Object `{obj_handle}`)"

            if self.generate_debug_images:
                # use DebugVisualizer to get 6-axis view of the object
                dvb = hab_debug_vis.DebugVisualizer(
                    sim=sim,
                    output_path=self.output_directory,
                    default_sensor_uuid="color_sensor",
                )
                dvb.peek_rigid_object(
                    obj, peek_all_axis=True, additional_savefile_prefix=pr_id + "_"
                )

            # run evaluation
            pr_raycast_results = run_pairwise_raycasts(
                self.gt_data[obj_handle]["test_points"], sim
            )
            self.gt_data[obj_handle]["raycasts"][pr_id] = {
                "results": pr_raycast_results
            }

            # undo template modification
            obj_template.render_asset_handle = render_asset
            otm.register_template(obj_template)

    def compute_receptacle_access_metrics(
        self, obj_handle: str, use_gt=False, acces_ratio_threshold: float = 0.1
    ):
        """
        Compute a heuristic for the accessibility of all Receptacles for an object.
        Uses raycasting from previously sampled receptacle locations to approximate how open a particular receptacle is.
        :param use_gt: Compute the metric for the ground truth shape instead of the currently active collision proxy (default)
        :param acces_ratio_threshold: The ratio of accessible:blocked rays necessary for a Receptacle point to be considered accessible
        """
        # algorithm:
        # For each receptacle, r:
        #  For each sample point, s:
        #    Generate `num_point_rays` directions, d (length bb diagnonal) and Ray(origin=s+d, direction=d)
        #    For each ray:
        #      If dist > 1, success, otherwise failure
        #
        # metrics:
        # - %rays
        # - %points w/ success% > eps(10%) #call these successful/accessible
        # - average % for points
        # ? how to get regions?
        # ? debug draw this metric?
        # ? how to diff b/t gt and pr?

        print(f"compute_receptacle_access_metrics - obj_handle = {obj_handle}")

        # start with empty scene or stage as scene:
        scene_name = "NONE"
        if use_gt:
            scene_name = self.gt_data[obj_handle]["stage_template_name"]
        cfg = self.get_cfg_with_mm(scene=scene_name)
        with habitat_sim.Simulator(cfg) as sim:
            obj_rec_data = self.gt_data[obj_handle]["receptacles"]
            shape_id = "gt"
            obj = None
            if not use_gt:
                # load the object
                obj = sim.get_rigid_object_manager().add_object_by_template_handle(
                    obj_handle
                )
                assert obj.is_alive, "Object was not added correctly."

                # when evaluating multiple proxy shapes, need unique ids:
                shape_id = f"pr{self.gt_data[obj_handle]['next_proxy_id']-1}"

            # gather hemisphere rays scaled to object's size
            # NOTE: because the receptacle points can be located anywhere in the bounding box, raycast radius must be bb diagonal length
            ray_sphere_radius = self.gt_data[obj_handle]["scene_bb"].size().length()
            assert ray_sphere_radius > 0, "otherwise we have an error"
            ray_sphere_points = get_scaled_hemisphere_vectors(ray_sphere_radius)

            # save a list of point accessibility scores for debugging and visualization
            receptacle_point_access_scores = {}
            dvb = hab_debug_vis.DebugVisualizer(
                sim=sim,
                output_path=self.output_directory,
                default_sensor_uuid="color_sensor",
            )

            # collect hemisphere raycast samples for all receptacle sample points
            for receptacle_name in obj_rec_data.keys():
                if "results" not in obj_rec_data[receptacle_name]:
                    obj_rec_data[receptacle_name]["results"] = {}
                assert (
                    shape_id not in obj_rec_data[receptacle_name]["results"]
                ), f" overwriting results for {shape_id}"
                obj_rec_data[receptacle_name]["results"][shape_id] = {}
                sample_point_ray_results: List[
                    List[habitat_sim.physics.RaycastResults]
                ] = []
                sample_point_access_ratios: List[float] = []
                # access rate is percent of "accessible" points apssing the threshold
                receptacle_access_rate = 0
                # access score is average accessibility of points
                receptacle_access_score = 0
                sample_points = obj_rec_data[receptacle_name]["sample_points"]
                for sample_point in sample_points:
                    # NOTE: rays must originate outside the shape because origins inside a convex will not collide.
                    # move ray origins to new point location
                    hemi_rays = [
                        habitat_sim.geo.Ray(v + sample_point, -v)
                        for v in ray_sphere_points
                    ]
                    # rays are not unit length, so use local max_distance==1 ray length
                    ray_results = [
                        sim.cast_ray(ray=ray, max_distance=1.0) for ray in hemi_rays
                    ]
                    sample_point_ray_results.append(ray_results)

                    # compute per-point access metrics
                    blocked_rays = len([rr for rr in ray_results if rr.has_hits()])
                    sample_point_access_ratios.append(
                        (len(ray_results) - blocked_rays) / len(ray_results)
                    )
                    receptacle_access_score += sample_point_access_ratios[-1]
                    if sample_point_access_ratios[-1] > acces_ratio_threshold:
                        receptacle_access_rate += 1
                    receptacle_point_access_scores[
                        receptacle_name
                    ] = sample_point_access_ratios

                receptacle_access_score /= len(sample_points)
                receptacle_access_rate /= len(sample_points)

                obj_rec_data[receptacle_name]["results"][shape_id][
                    "sample_point_ray_results"
                ] = sample_point_ray_results
                obj_rec_data[receptacle_name]["results"][shape_id][
                    "receptacle_access_score"
                ] = receptacle_access_score
                obj_rec_data[receptacle_name]["results"][shape_id][
                    "receptacle_access_rate"
                ] = receptacle_access_rate
                print(f" receptacle_name = {receptacle_name}")
                print(f" receptacle_access_score = {receptacle_access_score}")
                print(f" receptacle_access_rate = {receptacle_access_rate}")

                if self.generate_debug_images:
                    # generate receptacle access debug images
                    # 1a Show missed rays vs 1b hit rays
                    debug_lines = []
                    for ray_results in obj_rec_data[receptacle_name]["results"][
                        shape_id
                    ]["sample_point_ray_results"]:
                        for hit_record in ray_results:
                            if not hit_record.has_hits():
                                debug_lines.append(
                                    (
                                        [
                                            hit_record.ray.origin,
                                            hit_record.ray.origin
                                            + hit_record.ray.direction,
                                        ],
                                        mn.Color4.green(),
                                    )
                                )
                    if use_gt:
                        dvb.peek_scene(
                            peek_all_axis=True,
                            additional_savefile_prefix=f"gt_{receptacle_name}_access_rays_",
                            debug_lines=debug_lines,
                            debug_circles=None,
                        )
                    else:
                        dvb.peek_rigid_object(
                            obj,
                            peek_all_axis=True,
                            additional_savefile_prefix=f"{shape_id}_{receptacle_name}_access_rays_",
                            debug_lines=debug_lines,
                            debug_circles=None,
                        )

                    # 2 Show only rec points colored by "access" metric or percentage
                    debug_circles = []
                    color_r = mn.Color4.red().to_xyz()
                    color_g = mn.Color4.green().to_xyz()
                    delta = color_g - color_r
                    for point_access_ratio, point in zip(
                        receptacle_point_access_scores[receptacle_name],
                        obj_rec_data[receptacle_name]["sample_points"],
                    ):
                        point_color_xyz = color_r + delta * point_access_ratio
                        debug_circles.append(
                            (
                                point,
                                0.02,
                                mn.Vector3(0, 1, 0),
                                mn.Color4.from_xyz(point_color_xyz),
                            )
                        )
                    # use DebugVisualizer to get 6-axis view of the object
                    if use_gt:
                        dvb.peek_scene(
                            peek_all_axis=True,
                            additional_savefile_prefix=f"gt_{receptacle_name}_point_ratios_",
                            debug_lines=None,
                            debug_circles=debug_circles,
                        )
                    else:
                        dvb.peek_rigid_object(
                            obj,
                            peek_all_axis=True,
                            additional_savefile_prefix=f"{shape_id}_{receptacle_name}_point_ratios_",
                            debug_lines=None,
                            debug_circles=debug_circles,
                        )
                    # obj_rec_data[receptacle_name]["results"][shape_id]["sample_point_ray_results"]

    def compute_receptacle_stability(
        self,
        obj_handle: str,
        use_gt: bool = False,
        cyl_radius: float = 0.04,
        cyl_height: float = 0.15,
        accepted_height_error: float = 0.02,
    ):
        """
        Try to place a dynamic cylinder on the receptacle points. Record snap error and physical stability.

        :param obj_handle: The object to evaluate.
        :param use_gt: Compute the metric for the ground truth shape instead of the currently active collision proxy (default)
        :param cyl_radius: Radius of the test cylinder object (default similar to food can)
        :param cyl_height: Height of the test cylinder object (default similar to food can)
        :param accepted_height_error: The acceptacle distance from sample point to snapped point considered successful (meters)
        """

        constructed_cyl_obj_handle = f"cylinder_test_obj_r{cyl_radius}_h{cyl_height}"
        otm = self.mm.object_template_manager
        if not otm.get_library_has_handle(constructed_cyl_obj_handle):
            # ensure that a correctly sized asset mesh is available
            atm = self.mm.asset_template_manager
            half_length = (cyl_height / 2.0) / cyl_radius
            custom_prim_name = f"cylinderSolid_rings_1_segments_12_halfLen_{half_length}_useTexCoords_false_useTangents_false_capEnds_true"

            if not atm.get_library_has_handle(custom_prim_name):
                # build the primitive template
                cylinder_prim_handle = atm.get_template_handles("cylinderSolid")[0]
                cyl_template = atm.get_template_by_handle(cylinder_prim_handle)
                # default radius==1, so we modify the half-length
                cyl_template.half_length = half_length
                atm.register_template(cyl_template)

            assert atm.get_library_has_handle(
                custom_prim_name
            ), "primitive asset creation bug."

            if not otm.get_library_has_handle(constructed_cyl_obj_handle):
                default_cyl_template_handle = otm.get_synth_template_handles(
                    "cylinderSolid"
                )[0]
                default_cyl_template = otm.get_template_by_handle(
                    default_cyl_template_handle
                )
                default_cyl_template.render_asset_handle = custom_prim_name
                default_cyl_template.collision_asset_handle = custom_prim_name
                # our prim asset has unit radius, so scale the object by desired radius
                default_cyl_template.scale = mn.Vector3(cyl_radius)
                otm.register_template(default_cyl_template, constructed_cyl_obj_handle)
                assert otm.get_library_has_handle(constructed_cyl_obj_handle)

        assert (
            len(self.gt_data[obj_handle]["receptacles"].keys()) > 0
        ), "Object must have receptacle sampling metadata defined. See `setup_obj_gt`"

        # start with empty scene or stage as scene:
        scene_name = "NONE"
        if use_gt:
            scene_name = self.gt_data[obj_handle]["stage_template_name"]
        cfg = self.get_cfg_with_mm(scene=scene_name)
        with habitat_sim.Simulator(cfg) as sim:
            dvb = hab_debug_vis.DebugVisualizer(
                sim=sim,
                output_path=self.output_directory,
                default_sensor_uuid="color_sensor",
            )
            # load the object
            rom = sim.get_rigid_object_manager()
            obj = None
            support_obj_ids = [-1]
            shape_id = "gt"
            if not use_gt:
                obj = rom.add_object_by_template_handle(obj_handle)
                support_obj_ids = [obj.object_id]
                assert obj.is_alive, "Object was not added correctly."
                # when evaluating multiple proxy shapes, need unique ids:
                shape_id = f"pr{self.gt_data[obj_handle]['next_proxy_id']-1}"

            # add the test object
            cyl_test_obj = rom.add_object_by_template_handle(constructed_cyl_obj_handle)
            cyl_test_obj_com_height = cyl_test_obj.root_scene_node.cumulative_bb.max[1]
            assert cyl_test_obj.is_alive, "Test object was not added correctly."

            # evaluation the sample points for each receptacle
            rec_data = self.gt_data[obj_handle]["receptacles"]
            for rec_name in rec_data.keys():
                sample_points = rec_data[rec_name]["sample_points"]

                failed_snap = 0
                failed_by_distance = 0
                failed_unstable = 0
                for sample_point in sample_points:
                    cyl_test_obj.translation = sample_point
                    cyl_test_obj.rotation = mn.Quaternion.identity_init()
                    # snap check
                    success = snap_down(
                        sim, cyl_test_obj, support_obj_ids=support_obj_ids, vdb=dvb
                    )
                    if success:
                        expected_height_error = abs(
                            (cyl_test_obj.translation - sample_point).length()
                            - cyl_test_obj_com_height
                        )
                        if expected_height_error > accepted_height_error:
                            failed_by_distance += 1
                            continue

                        # physical stability analysis
                        snap_position = cyl_test_obj.translation
                        identity_q = mn.Quaternion.identity_init()
                        displacement_limit = 0.04  # meters
                        rotation_limit = mn.Rad(0.1)  # radians
                        max_sim_time = 3.0
                        dt = 0.5
                        start_time = sim.get_world_time()
                        object_is_stable = True
                        while sim.get_world_time() - start_time < max_sim_time:
                            sim.step_world(dt)
                            linear_displacement = (
                                cyl_test_obj.translation - snap_position
                            ).length()
                            # NOTE: negative quaternion represents the same rotation, but gets a different angle error so check both
                            angular_displacement = min(
                                mn.math.angle(cyl_test_obj.rotation, identity_q),
                                mn.math.angle(-1 * cyl_test_obj.rotation, identity_q),
                            )
                            if (
                                angular_displacement > rotation_limit
                                or linear_displacement > displacement_limit
                            ):
                                object_is_stable = False
                                break
                            if not cyl_test_obj.awake:
                                # the object has settled, no need to continue simulating
                                break
                        # NOTE: we assume that if the object has not moved past the threshold in 'max_sim_time', then it must be stabel enough
                        if not object_is_stable:
                            failed_unstable += 1
                    else:
                        failed_snap += 1

                successful_points = (
                    len(sample_points)
                    - failed_snap
                    - failed_by_distance
                    - failed_unstable
                )
                success_ratio = successful_points / len(sample_points)
                print(
                    f"{shape_id}: receptacle '{rec_name}' success_ratio = {success_ratio}"
                )
                print(
                    f"     failed_snap = {failed_snap}|failed_by_distance = {failed_by_distance}|failed_unstable={failed_unstable}|total={len(sample_points)}"
                )
                # TODO: visualize this error
                # TODO: record results for later processing

    def compute_gt_errors(self, obj_handle: str) -> None:
        """
        Compute and cache all ground truth error metrics.
        Assumes `self.gt_data[obj_handle]["raycasts"]` keys are different raycast results to be compared.
          'gt' must exist.
        """

        assert (
            obj_handle in self.gt_data
        ), f"`{obj_handle}` does not have any entry in gt_data: {self.gt_data.keys()}. Call to `setup_obj_gt(obj_handle)` required."
        assert (
            len(self.gt_data[obj_handle]["raycasts"]) > 1
        ), "Only gt results acquired, no error to compute. Try `compute_proxy_metrics` or `compute_baseline_metrics`."
        assert (
            "gt" in self.gt_data[obj_handle]["raycasts"]
        ), "Must have a ground truth to compare against. Should be generated in `setup_obj_gt(obj_handle)`."

        for key in self.gt_data[obj_handle]["raycasts"].keys():
            if (
                key != "gt"
                and "normalized_errors" not in self.gt_data[obj_handle]["raycasts"][key]
            ):
                normalized_error = get_raycast_results_cumulative_error_metric(
                    self.gt_data[obj_handle]["raycasts"]["gt"]["results"],
                    self.gt_data[obj_handle]["raycasts"][key]["results"],
                )
                self.gt_data[obj_handle]["raycasts"][key][
                    "normalized_errors"
                ] = normalized_error

    def grid_search_vhacd_params(self, obj_template_handle: str):
        """
        For a specified set of search parameters, try all combinations by:
        1. computing new proxy shape
        2. evaluating new proxy shape across various metrics
        """

        # vhacd_test_params = habitat_sim.VHACDParameters()

        # vhacd_test_params.max_num_vertices_per_ch = 64
        # vhacd_test_params.max_convex_hulls = 1024
        # vhacd_test_params.plane_downsampling = 4 #1-16
        # vhacd_test_params.convex_hull_downsampling = 4 #1-16

        # vhacd_test_params.alpha = 0.05 #bias towards symmetry [0-1]
        # vhacd_test_params.beta = 0.05 #bias toward revolution axes [0-1]

        # vhacd_test_params.mode = 0 #0=voxel, 1=tetrahedral
        # vhacd_test_params.pca = 0 #1=use PCA normalization

        param_ranges = {
            # "pca": (0,1), #pca seems worse, no speed improvement
            # "mode": (0,1), #tetrahedral mode seems worse
            "alpha": (0.05, 0.1),
            "beta": (0.05, 0.1),
            "plane_downsampling": [2],
            "convex_hull_downsampling": [2],
            "max_num_vertices_per_ch": (16, 32),
            # "max_convex_hulls": (8,16,32,64),
            "max_convex_hulls": (16, 32, 64),
            "resolution": [200000],
        }

        permutations = [[]]

        # permute variations
        for attr, values in param_ranges.items():
            new_permutations = []
            for v in values:
                for permutation in permutations:
                    extended_permutation = [(attr, v)]
                    for setting in permutation:
                        extended_permutation.append(setting)
                    new_permutations.append(extended_permutation)
            permutations = new_permutations
        print(f"Parameter permutations = {len(permutations)}")
        for setting in permutations:
            print(f"    {setting}")

        vhacd_start_time = time.time()
        vhacd_iteration_times = {}
        # evaluate VHACD settings
        for setting in permutations:
            vhacd_params = habitat_sim.VHACDParameters()
            setting_string = ""
            for attr, val in setting:
                setattr(vhacd_params, attr, val)
                setting_string += f" '{attr}'={val}"
            vhacd_iteration_time = time.time()
            self.compute_vhacd_col_shape(obj_template_handle, vhacd_params)

            self.compute_proxy_metrics(obj_template_handle)
            proxy_id = f"pr{self.gt_data[obj_template_handle]['next_proxy_id']-1}"
            if "vhacd_settings" not in self.gt_data[obj_template_handle]:
                self.gt_data[obj_template_handle]["vhacd_settings"] = {}
            self.gt_data[obj_template_handle]["vhacd_settings"][
                proxy_id
            ] = setting_string

            if self.compute_receptacle_useability_metrics:
                self.compute_receptacle_access_metrics(obj_handle=obj_template_handle)
            vhacd_iteration_times[proxy_id] = time.time() - vhacd_iteration_time

        print(f"Total VHACD time = {time.time()-vhacd_start_time}")
        print("    Iteration times = ")
        for proxy_id, settings in self.gt_data[obj_template_handle][
            "vhacd_settings"
        ].items():
            print(f"     {proxy_id} - {settings} - {vhacd_iteration_times[proxy_id]}")

    def compute_vhacd_col_shape(
        self, obj_template_handle: str, vhacd_params: habitat_sim.VHACDParameters
    ) -> None:
        """
        Compute a new VHACD convex decomposition for the object and set it as the active collision proxy.
        """

        new_template_handle = None

        otm = self.mm.object_template_manager
        matching_obj_handles = otm.get_file_template_handles(obj_template_handle)
        assert (
            len(matching_obj_handles) == 1
        ), f"None or many matching handles to substring `{obj_template_handle}`: {matching_obj_handles}"
        obj_template = otm.get_template_by_handle(matching_obj_handles[0])
        render_asset = obj_template.render_asset_handle
        render_asset_path = os.path.abspath(render_asset)

        cfg = self.get_cfg_with_mm()
        with habitat_sim.Simulator(cfg) as sim:
            new_template_handle = sim.apply_convex_hull_decomposition(
                render_asset_path, vhacd_params, save_chd_to_obj=True
            )

        # set the collision asset
        matching_vhacd_handles = otm.get_file_template_handles(new_template_handle)
        assert (
            len(matching_vhacd_handles) == 1
        ), f"None or many matching VHACD handles to substring `{new_template_handle}`: {matching_vhacd_handles}"

        vhacd_template = otm.get_template_by_handle(matching_vhacd_handles[0])

        obj_template.collision_asset_handle = vhacd_template.collision_asset_handle

        otm.register_template(obj_template)

    def cache_global_results(self) -> None:
        """
        Cache the current global cumulative results.
        Do this after an object's computation is done (compute_gt_errors) before cleaning the gt data.
        """

        for obj_handle in self.gt_data.keys():
            if obj_handle not in self.results:
                self.results[obj_handle] = {}
            for key in self.gt_data[obj_handle]["raycasts"].keys():
                if (
                    key != "gt"
                    and "normalized_errors" in self.gt_data[obj_handle]["raycasts"][key]
                ):
                    if "normalized_errors" not in self.results[obj_handle]:
                        self.results[obj_handle]["normalized_errors"] = {}
                    self.results[obj_handle]["normalized_errors"][key] = self.gt_data[
                        obj_handle
                    ]["raycasts"][key]["normalized_errors"]

            if self.compute_receptacle_useability_metrics:
                self.results[obj_handle]["receptacle_info"] = {}
                # cache the receptacle access metrics for CSV save
                for rec_key in self.gt_data[obj_handle]["receptacles"].keys():
                    self.results[obj_handle]["receptacle_info"][rec_key] = {}
                    assert (
                        "results" in self.gt_data[obj_handle]["receptacles"][rec_key]
                    ), "Must run 'compute_receptacle_access_metrics' before caching global receptacle data."
                    rec_results = self.gt_data[obj_handle]["receptacles"][rec_key][
                        "results"
                    ]

                    # access rate and score
                    for metric in ["receptacle_access_score", "receptacle_access_rate"]:
                        for shape_id in rec_results.keys():
                            if (
                                metric
                                not in self.results[obj_handle]["receptacle_info"][
                                    rec_key
                                ]
                            ):
                                self.results[obj_handle]["receptacle_info"][rec_key][
                                    metric
                                ] = {}
                            self.results[obj_handle]["receptacle_info"][rec_key][
                                metric
                            ][shape_id] = rec_results[shape_id][metric]

    def save_results_to_csv(self, filename: str) -> None:
        """
        Save current global results to a csv file in the self.output_directory.
        """

        assert len(self.results) > 0, "There must be results to save."

        import csv

        filepath = os.path.join(self.output_directory, filename)

        # save normalized error csv
        with open(filepath + ".csv", "w") as f:
            writer = csv.writer(f, quoting=csv.QUOTE_ALL)
            # first collect all column names:
            existing_cols = []
            for obj_handle in self.results.keys():
                if "normalized_errors" in self.results[obj_handle]:
                    for key in self.results[obj_handle]["normalized_errors"]:
                        if key not in existing_cols:
                            existing_cols.append(key)
            # put the baselines first
            ordered_cols = ["object_handle"]
            if "empty" in existing_cols:
                ordered_cols.append("empty")
            if "bb" in existing_cols:
                ordered_cols.append("bb")
            for key in existing_cols:
                if key not in ordered_cols:
                    ordered_cols.append(key)
            # write column names row
            writer.writerow(ordered_cols)

            # write results rows
            for obj_handle in self.results.keys():
                row_data = [obj_handle]
                if "normalized_errors" in self.results[obj_handle]:
                    for key in ordered_cols:
                        if key != "object_handle":
                            if key in self.results[obj_handle]["normalized_errors"]:
                                row_data.append(
                                    self.results[obj_handle]["normalized_errors"][key]
                                )
                            else:
                                row_data.append("")
                writer.writerow(row_data)

        # export receptacle metrics to CSV
        if self.compute_receptacle_useability_metrics:
            rec_filepath = filepath + "_receptacle_metrics"
            with open(rec_filepath + ".csv", "w") as f:
                writer = csv.writer(f, quoting=csv.QUOTE_ALL)
                # first collect all column names:
                existing_cols = ["receptacle"]
                shape_ids = []
                metrics = []
                for obj_handle in self.results.keys():
                    if "receptacle_info" in self.results[obj_handle]:
                        for rec_key in self.results[obj_handle]["receptacle_info"]:
                            for metric in self.results[obj_handle]["receptacle_info"][
                                rec_key
                            ].keys():
                                if metric not in metrics:
                                    metrics.append(metric)
                                for shape_id in self.results[obj_handle][
                                    "receptacle_info"
                                ][rec_key][metric].keys():
                                    if shape_id not in shape_ids:
                                        shape_ids.append(shape_id)
                                    if shape_id + "-" + metric not in existing_cols:
                                        existing_cols.append(shape_id + "-" + metric)
                # write column names row
                writer.writerow(existing_cols)

                # write results rows
                for obj_handle in self.results.keys():
                    if "receptacle_info" in self.results[obj_handle]:
                        for rec_key in self.results[obj_handle]["receptacle_info"]:
                            rec_info = self.results[obj_handle]["receptacle_info"][
                                rec_key
                            ]
                            row_data = [obj_handle + "_" + rec_key]
                            for metric in metrics:
                                for shape_id in shape_ids:
                                    if (
                                        metric in rec_info
                                        and shape_id in rec_info[metric]
                                    ):
                                        row_data.append(rec_info[metric][shape_id])
                                    else:
                                        row_data.append("")
                            writer.writerow(row_data)
        # TODO: add receptacle stability reporting

    def compute_and_save_results_for_objects(
        self, obj_handle_substrings: List[str], output_filename: str = "cpo_out"
    ) -> None:
        # first find all full object handles
        otm = self.mm.object_template_manager
        obj_handles = []
        for obj_h in obj_handle_substrings:
            # find the full handle
            matching_obj_handles = otm.get_file_template_handles(obj_h)
            assert (
                len(matching_obj_handles) == 1
            ), f"None or many matching handles to substring `{obj_h}`: {matching_obj_handles}"
            obj_handles.append(matching_obj_handles[0])

        print(f"Found handles: {obj_handles}.")
        print("Computing metrics:")
        # then compute metrics for all objects and cache
        for obix, obj_h in enumerate(obj_handles):
            print("-------------------------------")
            print(f"Computing metric for `{obj_h}`, {obix}|{len(obj_handles)}")
            print("-------------------------------")
            self.setup_obj_gt(obj_h)
            self.compute_baseline_metrics(obj_h)
            self.compute_proxy_metrics(obj_h)
            # receptacle metrics:
            if self.compute_receptacle_useability_metrics:
                self.compute_receptacle_stability(obj_h, use_gt=True)
                self.compute_receptacle_stability(obj_h)
                print(" GT Receptacle Metrics:")
                self.compute_receptacle_access_metrics(obj_h, use_gt=True)
                print(" PR Receptacle Metrics:")
                self.compute_receptacle_access_metrics(obj_h, use_gt=False)
            self.grid_search_vhacd_params(obj_h)
            self.compute_gt_errors(obj_h)
            self.cache_global_results()
            self.clean_obj_gt(obj_h)

        # then save results to file
        self.save_results_to_csv(output_filename)


def object_has_receptacles(
    object_template_handle: str,
    otm: habitat_sim.attributes_managers.ObjectAttributesManager,
) -> bool:
    """
    Returns whether or not an object has a receptacle defined in its config file.
    """
    # this prefix will be present for any entry which defines a receptacle
    receptacle_prefix_string = "receptacle_"

    object_template = otm.get_template_by_handle(object_template_handle)
    assert (
        object_template is not None
    ), f"No template matching handle {object_template_handle}."

    user_cfg = object_template.get_user_config()

    return any(
        sub_config_key.startswith(receptacle_prefix_string)
        for sub_config_key in user_cfg.get_subconfig_keys()
    )


def main():
    parser = argparse.ArgumentParser(
        description="Automate collision shape creation and validation."
    )
    parser.add_argument("--dataset", type=str, help="path to SceneDataset.")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="collision_shape_automation/",
        help="output directory for saved csv and images. Default = `./collision_shape_automation/`.",
    )
    # parser.add_argument(
    #    "--object-handle", type=str, help="handle identifying the object to evaluate."
    # )
    args = parser.parse_args()

    sim_settings = default_sim_settings.copy()
    sim_settings["scene_dataset_config_file"] = args.dataset
    # necessary for debug rendering
    sim_settings["sensor_height"] = 0
    sim_settings["width"] = 720
    sim_settings["height"] = 720
    sim_settings["clear_color"] = mn.Color4.magenta() * 0.5

    # one-off single object logic:
    # evaluate_collision_shape(args.object_handle, sim_settings)

    # use the CollisionProxyOptimizer to compute metrics for multiple objects
    cpo = CollisionProxyOptimizer(sim_settings, output_directory=args.output_dir)
    cpo.generate_debug_images = True

    # get all object handles
    otm = cpo.mm.object_template_manager
    all_handles = otm.get_file_template_handles()
    # get a subset with receptacles defined
    all_handles = [
        all_handles[i]
        for i in range(len(all_handles))
        if object_has_receptacles(all_handles[i], otm)
    ]
    print(f"Number of objects with receptacles = {len(all_handles)}")

    # NOTE: select objects for testing VHACD pipeline
    target_object_handles = [
        "01be253cbfd14b947e9dbe09d0b1959e97d72122",  # desk
        "01b65339d622bb9f89eb8fdd753a76cffc7eb8d6",  # shelves,
        "00ea83bf1b2544df87f6d52d02382c0bb75598c6",  # bookcase
        "00e388a751b3654216f2109ee073dc44f1241eee",  # counter
        "01d9fff2f701af7d5d40a7a5adad5bf40d4c49c8",  # round table
        "03c328fccef4975310314838e42b6dff06709b06",  # shelves
        "0110c7ff0e787bf98c9da923554ddea1484e4a3d",  # wood table
        "00366b86401aa16b702c21de49fd59b75ab9c57b",  # ratan sofa
    ]
    all_handles = [
        h for h in all_handles if any([t in h for t in target_object_handles])
    ]

    # indexed subset of the objects
    # all_handles = all_handles[1:2]

    # print(all_handles)
    cpo.compute_and_save_results_for_objects(all_handles)

    # testing objects
    # obj_handle1 = "0a5e809804911e71de6a4ef89f2c8fef5b9291b3"
    # obj_handle2 = "d1d1e0cdaba797ee70882e63f66055675c3f1e7f"
    # cpo.compute_and_save_results_for_objects([obj_handle1, obj_handle2])


if __name__ == "__main__":
    main()
