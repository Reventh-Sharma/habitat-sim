import json
import os
import time
from ntpath import basename

import git
import processor_utils as pcsu
import psutil
from colorama import Fore, init
from magnum import trade
from processor_settings import default_sim_settings
from processor_utils import (
    ANSICodes,
    Any,
    DatasetProcessorSim,
    Dict,
    List,
    RotationAxis,
    Tuple,
    mn,
    physics,
)

from habitat_sim import attributes, attributes_managers
from habitat_sim.logging import logger
from habitat_sim.utils import viz_utils as vut

repo = git.Repo(".", search_parent_directories=True)
HABITAT_SIM_PATH = repo.working_tree_dir


def record_revolving_obj(
    sim: DatasetProcessorSim,
    angle_delta: float,
) -> Dict[int, Any]:
    """ """
    observations = []
    for axis in list(RotationAxis):
        curr_angle = 0.0
        finished = False
        while curr_angle < 360.0:
            # determine if this iteration will push the object past
            # 360.0 degrees, meaning we are done
            if curr_angle + angle_delta >= 360.0:
                finished = True
                angle_delta = 360.0 - curr_angle
                curr_angle = 360.0

            # rotate about object's local x or y axis
            rot_rad = mn.Rad(mn.Deg(angle_delta))
            sim.curr_obj.rotate_local(rot_rad, mn.Vector3(axis))

            # save this observation in a buffer of frames
            observations.append(sim.get_sensor_observations())

            # update current rotation angle
            curr_angle += angle_delta

            # reset current rotation angle if it passed 360 degrees
            if finished:
                curr_angle = 360.0

    return observations


def record_asset_video(sim: DatasetProcessorSim) -> None:
    """
    Loop over each recording task specified in the config file, i.e. show bounding box,
    show collision asset, and show bullet collision mesh, then using the transforms
    of the agent and sensor, record the observations of the revolving ManagedBulletRigidObject,
    which is in Kinematic mode and just being displayed, not simulated. The object
    currently revolves 360 degrees once around its x-axis, then once around its y-axis for
    each task. Then save the cumulation of observations as a video file.
    :param sim: The Simulator instance.
    """
    # init video and rotation parameters
    video_vars: Dict[str, Any] = sim.sim_settings["video_vars"]
    tasks: Dict[str, bool] = video_vars.get("tasks")
    deg_per_sec = 360.0 / sim.sim_settings["video_vars"].get("revolution_dur")
    dt = 1.0 / sim.sim_settings["physics_vars"].get("fps")
    angle_delta = deg_per_sec * dt

    # init object transforms
    default_transforms = sim.sim_settings["default_transforms"]
    obj_rot = default_transforms.get("default_obj_rot")
    sim.curr_obj.translation = default_transforms.get("default_obj_pos")
    angle = mn.Rad(mn.Deg(obj_rot.get("angle")))
    axis = mn.Vector3(obj_rot.get("axis"))
    sim.curr_obj.rotation = mn.Quaternion.rotation(angle, axis)
    sim.curr_obj.motion_type = physics.MotionType.KINEMATIC

    # Loop over each recording task specified in the config file
    observations = []
    for task, required in tasks.items():
        if required == False:
            continue
        # record object rotating about its x-axis, then its y-axis
        pcsu.print_if_logging(ANSICodes.YELLOW.value + "draw " + task)
        sim.draw_task = task
        observations += record_revolving_obj(sim, angle_delta)

    # construct file path and write "observations" to video file
    video_file_dir = os.path.join(
        HABITAT_SIM_PATH, sim.sim_settings["output_paths"].get("video")
    )
    obj_handle = sim.curr_obj.handle.replace("_:0000", "")
    video_file_prefix = sim.sim_settings["output_paths"].get("output_file_prefix")
    video_file_prefix += f"_{obj_handle}"
    file_path = pcsu.create_unique_filename(video_file_dir, ".mp4", video_file_prefix)
    vut.make_video(
        observations,
        "color_sensor",
        "color",
        file_path,
        open_vid=False,
    )


def process_asset_mem_usage(
    importer: trade.AbstractImporter,
    template: attributes.ObjectAttributes,
) -> List[str]:
    """
    Use the trade.AbstractImporter class to query data size of mesh and image
    of asset
    :param importer: AbstractImporter to open files and get mem size info
    :param template: ObjectAttributes to get render asset and collision asset
    """
    # construct absolute file paths for render and collision assets
    render_asset_handle = template.render_asset_handle
    collision_asset_handle = template.collision_asset_handle
    asset_paths: List[str] = [
        os.path.join(HABITAT_SIM_PATH, render_asset_handle),
        os.path.join(HABITAT_SIM_PATH, collision_asset_handle),
    ]

    # get the render and collision asset file names for CSV
    render_asset_filename = basename(render_asset_handle)
    collision_asset_filename = basename(collision_asset_handle)

    # Log render asset handle and collision asset handle
    text_format = Fore.GREEN
    pcsu.print_if_logging(
        text_format
        + f"-render: {render_asset_handle}\n"
        + f"-collision: {collision_asset_handle}\n"
    )

    # Create variables to store mesh data
    mesh_count = 0
    index_data_size = 0  # bytes
    vertex_data_size = 0  # bytes
    image_count = 0
    image_data_size = 0  # bytes

    # Calculate mesh data for both render and collision assets
    for asset_path in asset_paths:
        importer.open_file(asset_path)

        # Get mesh data
        mesh_count += importer.mesh_count
        for i in range(importer.mesh_count):
            mesh: trade.MeshData = importer.mesh(i)
            index_data_size += len(mesh.index_data)
            vertex_data_size += len(mesh.vertex_data)

        # Get image data
        for i in range(importer.image2d_count):
            image_count += importer.image2d_level_count(i)
            for j in range(importer.image2d_level_count(i)):
                image: trade.ImageData2D = importer.image2d(i, j)
                image_data_size += len(image.data)

    total_mesh_data_size = index_data_size + vertex_data_size

    # return results as a list of strings formatted for csv rows
    mesh_count_units = "mesh" if mesh_count == 1 else "meshes"
    image_count_units = "image" if image_count == 1 else "images"
    return [
        render_asset_filename,
        collision_asset_filename,
        f"{mesh_count} {mesh_count_units}",
        pcsu.get_mem_size_str(index_data_size),
        pcsu.get_mem_size_str(vertex_data_size),
        pcsu.get_mem_size_str(total_mesh_data_size),
        f"{image_count} {image_count_units}",
        pcsu.get_mem_size_str(image_data_size),
    ]


def process_asset_render_time() -> List[str]:
    return ["..."]


def process_asset_physics(sim: DatasetProcessorSim) -> List[str]:
    """
    Run series of tests on asset to see how it responds in physics simulations.
    We snap an object down onto the surface below, then see how long it takes
    for the object to stabilize and become idle.
    :param sim: The Simulator instance.
    """
    # we must test object in 6 different orientations, each corresponding to a face
    # of an imaginary cube bounding the object. Each rotation in rotations is of the form:
    # (angle, (axis.x, axis.y, axis.z)) where angle is in degrees
    rotations: List[Tuple] = [
        (mn.Rad(mn.Deg(rotation[0])), mn.Vector3(rotation[1]))
        for rotation in sim.sim_settings["sim_test_rotations"]
    ]
    wait_times: List[float] = [0.0] * len(rotations)
    translation_deltas: List[float] = [0.0] * len(rotations)
    rotation_deltas: List[mn.Quaternion] = [mn.Quaternion.identity_init()] * len(
        rotations
    )
    sim_time_ratios: List[float] = [0.0] * len(rotations)

    # Print object that we will be imminently simulating
    text_format = ANSICodes.BRIGHT_RED.value
    pcsu.print_if_logging(
        text_format
        + f"\nstart simulating {basename(sim.curr_obj.creation_attributes.handle)}"
        + pcsu.section_divider
    )

    # Loop over the 6 rotations and simulate snapping the object down and waiting for
    # it to become idle (at least until "max_wait_time" from the config file expires)
    default_pos = sim.sim_settings["default_transforms"].get("default_obj_pos")
    dt = 1.0 / sim.sim_settings["physics_vars"].get("fps")  # seconds
    max_wait_time = sim.sim_settings["physics_vars"].get("max_wait_time")  # seconds
    for i in range(len(rotations)):

        # Reset object state with new rotation using angle-axis to construct
        # a quaternion. If axis is (0, 0, 0), that means there is no rotation
        sim.curr_obj.motion_type = physics.MotionType.DYNAMIC
        sim.curr_obj.awake = True
        sim.curr_obj.translation = default_pos
        angle = rotations[i][0]
        axis = rotations[i][1]
        if axis.is_zero():
            sim.curr_obj.rotation = mn.Quaternion.identity_init()
        else:
            sim.curr_obj.rotation = mn.Quaternion.rotation(angle, axis)

        # snap rigid object to surface below
        success = pcsu.snap_down_object(sim, sim.curr_obj)
        if not success:
            logger.warning(
                ANSICodes.BRIGHT_RED.value
                + "dataset_object_processor.process_asset_physics(...) - snapping failed"
            )
        snap_pos: mn.Vector3 = sim.curr_obj.translation
        snap_rot: mn.Quaternion = sim.curr_obj.rotation

        # simulate until rigid object becomes idle or time limit from config file runs out
        sim_steps: int = 0
        while sim.curr_obj.awake and wait_times[i] < max_wait_time:
            sim_steps += 1
            start_sim_time = time.time()
            sim.step_physics(dt)
            end_sim_time = time.time()
            sim_time_ratios[i] += (end_sim_time - start_sim_time) / dt
            wait_times[i] += dt

        # store final information once object becomes idle or it times out
        wait_times[i] = round(wait_times[i], 3)
        translation_deltas[i] = (sim.curr_obj.translation - snap_pos).length()
        rotation_deltas[i] = sim.curr_obj.rotation * snap_rot.conjugated()
        sim_time_ratios[i] /= sim_steps

    # convert results to lists of strings for csv file
    time_units = sim.sim_settings["physics_vars"].get("time_units")
    times_as_strs = [
        "****timed out****" if t >= max_wait_time else f"{t} {time_units}"
        for t in wait_times
    ]
    decimal = 3
    translation_deltas_strs = [f"{round(t, decimal)} units" for t in translation_deltas]
    decimal = 1
    angle_units = sim.sim_settings["physics_vars"].get("angle_units")
    rotation_deltas_strs = [
        f"angle:  {round(float(mn.Deg(r.angle())), decimal)} {angle_units}\n"
        + f"axis:  ({round(r.axis().x, decimal)}, {round(r.axis().y, decimal)}, {round(r.axis().z, decimal)})"
        for r in rotation_deltas
    ]
    decimal = 7
    sim_time_strs = [f"{round(ratio, decimal)}" for ratio in sim_time_ratios]

    # return concatenated list of physics results formatted for csv file row
    return (
        [f"({round(max_wait_time, 3)} {time_units} max)"]
        + times_as_strs
        + [""]
        + translation_deltas_strs
        + [""]
        + rotation_deltas_strs
        + [""]
        + sim_time_strs
    )


def process_asset(
    sim: DatasetProcessorSim,
    importer: trade.AbstractImporter,
    handle: str,
    obj_template_mgr: attributes_managers.ObjectAttributesManager,
) -> List[str]:
    """
    Depending on what the user specifies in the dataset_processor_config.json file,
    use the trade.AbstractImporter class to query data size of mesh and image
    of asset and how the asset behaves during physics simulations. Likewise,
    make a recording of the object in Kinematic mode displaying any/all of its
    bounding box, collision asset, and bullet collision mesh.
    :param sim: Simulator instance
    :param importer: AbstractImporter, used to process memory stats of the mesh
    :param handle: template handle of the asset to test from ObjectAttributes
    :param obj_template_mgr: the ObjectAttributes of the asset to test
    """
    # Get memory state before and after loading object with RigidObjectManager,
    # then use psutil to get a sense of how much RAM was used during the
    # loading process
    rigid_obj_mgr = sim.get_rigid_object_manager()
    start_mem = psutil.virtual_memory()._asdict()
    sim.curr_obj = rigid_obj_mgr.add_object_by_template_handle(handle)
    end_mem = psutil.virtual_memory()._asdict()

    # Get average deltas of each memory metric specified in the config file.
    # The variable "subtract_order" below is either -1 or 1. 1 means the delta is
    # calculated as (end - start), whereas -1 means (start - end). e.g. Data "used"
    # should be higher after loading, so subtract_order == 1, but data "free"
    # should be higher before loading, so subtract_order == -1
    metrics: List[str] = sim.sim_settings["mem_metrics_to_use"]
    avg_ram_delta = 0  # bytes
    for metric in metrics:
        subtract_order = sim.sim_settings["mem_delta_order"].get(metric)
        # "percent" isn't calculated in bytes, so skip it
        if metric != "percent":
            avg_ram_delta += (
                end_mem.get(metric) - start_mem.get(metric)
            ) * subtract_order

    avg_ram_delta /= len(metrics)
    avg_ram_used_str = pcsu.get_mem_size_str(avg_ram_delta)

    # TODO: remove this when I figure out why ram usage is sometimes negative
    global negative_ram_count
    if avg_ram_delta < 0:
        negative_ram_count += 1
        avg_ram_used_str = "****" + avg_ram_used_str + "****"

    # Print memory usage info before and after loading object
    pcsu.print_mem_usage_info(start_mem, end_mem, avg_ram_used_str)

    # Log object template handle if "silent" is false in the config file
    text_format = Fore.GREEN
    pcsu.print_if_logging(
        text_format
        + "\n"
        + "Handles"
        + pcsu.section_divider
        + "\n"
        + f"-template: {handle}\n"
    )

    # Get object attributes by template handle and associated mesh assets
    template = obj_template_mgr.get_template_by_handle(handle)

    # run object through tests defined in dataset_processor_config.json file
    csv_row: List[str] = []
    if sim.sim_settings["outputs"].get("csv"):
        data_to_collect = sim.sim_settings["data_to_collect"]
        csv_row += [basename(handle)]
        if data_to_collect.get("memory_data"):
            data = ["", avg_ram_used_str] + process_asset_mem_usage(importer, template)
            csv_row += data
        if data_to_collect.get("render_time_ratio"):
            data = [""] + process_asset_render_time()
            csv_row += data
        if data_to_collect.get("physics_data"):
            data = [""] + process_asset_physics(sim)
            csv_row += data

    # record video of object if denoted in dataset_processor_config.json file
    if sim.sim_settings["outputs"].get("video"):
        record_asset_video(sim)

    # remove this object so the next one can be added without interacting
    # with the previous one
    rigid_obj_mgr.remove_all_objects()

    # return results as a list of strings formatted for csv rows
    return csv_row


def process_dataset(
    sim: DatasetProcessorSim,
) -> None:
    """
    Load and process dataset objects using template handles
    :param sim: Simulator instance
    """
    dataset_path = sim.sim_settings["scene_dataset_config_file"]
    metadata_mediator = sim.metadata_mediator
    if (
        metadata_mediator is None
        or metadata_mediator.dataset_exists(dataset_path) is False
    ):
        raise RuntimeError(
            "process_dataset(...): No meta data mediator or dataset exists."
        )

    # get dataset that is currently being used by the simulator
    active_dataset: str = metadata_mediator.active_dataset
    text_format = ANSICodes.BRIGHT_BLUE.value + ANSICodes.BOLD.value
    pcsu.print_if_logging(text_format + "\nActive Dataset" + pcsu.section_divider)
    text_format = ANSICodes.BRIGHT_BLUE.value
    pcsu.print_if_logging(text_format + f"{active_dataset}\n")

    # Get ObjectAttributesManager for objects from dataset, load the dataset,
    # and store all the object template handles in a List
    obj_template_mgr = sim.get_object_template_manager()
    obj_template_mgr.load_configs(dataset_path)
    object_template_handles = obj_template_mgr.get_file_template_handles("")

    # Init vars to store the list of rows formatted for a csv file, as well as a
    # trade.AbstractImporter to assess the memory usage of the assets
    csv_rows: List[List[str]] = []
    manager = trade.ImporterManager()
    importer = manager.load_and_instantiate("AnySceneImporter")

    # loop over the assets specified in the config file, starting with index
    # "start_obj_index" and proceeding for "num_objects" iterations of the loop.
    # If "start_obj_index" and/or "num_objects" is not specified in the config file,
    # or is not an int, process every asset in the dataset
    start_index = sim.sim_settings["start_obj_index"]
    num_objs = sim.sim_settings["num_objects"]
    if not isinstance(start_index, int) or not isinstance(num_objs, int):
        start_index = 0
        num_objs = len(object_template_handles)

    for i in range(num_objs):
        if i >= len(object_template_handles):
            break
        handle = object_template_handles[start_index + i]
        row = process_asset(sim, importer, handle, obj_template_mgr)
        csv_rows.append(row)

    # Write csv if specified in the config file. "headers" stores the titles of
    # each csv column.
    if sim.sim_settings["outputs"].get("csv"):
        headers = pcsu.get_csv_headers(sim)
        csv_dir_path = os.path.join(
            HABITAT_SIM_PATH, sim.sim_settings["output_paths"].get("csv")
        )
        csv_file_prefix = sim.sim_settings["output_paths"].get("output_file_prefix")
        pcsu.create_csv_file(headers, csv_rows, csv_dir_path, csv_file_prefix)

    # clean up
    importer.close()

    # return list of rows to be written to csv file
    return csv_rows


def main() -> None:
    """
    Create Simulator, parse dataset (which also records a video if requested),
    then writes a csv file if requested
    """
    # parse arguments from command line: scene, dataset, if we process physics
    args = pcsu.build_parser().parse_args()

    # setup colorama terminal color printing so that format and color reset
    # after each pcsu.print_if_logging() statement
    init(autoreset=True)

    # Populate sim_settings with info from dataset_processor_config.json file
    sim_settings: Dict[str, Any] = default_sim_settings
    with open(os.path.join(HABITAT_SIM_PATH, args.config_file_path)) as config_json:
        pcsu.update_sim_settings(sim_settings, json.load(config_json))

    # Configure and make simulator
    sim = pcsu.configure_sim(sim_settings)

    # Print sim settings
    text_format = ANSICodes.PURPLE.value
    for key, value in sim_settings.items():
        pcsu.print_if_logging(text_format + f"{key} : {value}\n")

    # TODO: remove this when I figure out why ram usage is sometimes negative
    global negative_ram_count
    negative_ram_count = 0

    # Iterate through dataset objects and write csv and/or make video recording
    # if specified in the config file.
    process_dataset(sim)

    # TODO: remove this when I figure out why ram usage is sometimes negative
    text_format = ANSICodes.BRIGHT_MAGENTA.value
    pcsu.print_debug(
        text_format
        + f"negative RAM usage count: {negative_ram_count}"
        + pcsu.section_divider
    )


if __name__ == "__main__":
    main()
