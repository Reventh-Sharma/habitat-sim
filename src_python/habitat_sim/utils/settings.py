# Copyright (c) Meta Platforms, Inc. and its affiliates.
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import habitat_sim
import habitat_sim.agent

default_sim_settings = {
    "scene_dataset_config_file": "default",
    "scene": "NONE",
    "default_agent": 0,
    "seed": 1,
    "physics_config_file": "data/default.physics_config.json",
    "sensors": [
        {
            "uuid": "color_sensor",
            "width": 640,
            "height": 480,
            "sensor_height": 1.5,
            "hfov": 90,
            "sensor_subtype": habitat_sim.SensorSubType.PINHOLE,
            "sensor_type": habitat_sim.SensorType.COLOR,
            "position": [0, 1.5, 0],
            "channels": 3,
            "camera_type": habitat_sim.CameraSensorSpec,
        },
    ],
}


# build SimulatorConfiguration
def make_cfg(settings):
    sim_cfg = habitat_sim.SimulatorConfiguration()
    if "scene_dataset_config_file" in settings:
        sim_cfg.scene_dataset_config_file = settings["scene_dataset_config_file"]
    sim_cfg.frustum_culling = settings.get("frustum_culling", False)
    if "enable_physics" in settings:
        sim_cfg.enable_physics = settings["enable_physics"]
    if "physics_config_file" in settings:
        sim_cfg.physics_config_file = settings["physics_config_file"]
    if "scene_light_setup" in settings:
        sim_cfg.scene_light_setup = settings["scene_light_setup"]
    sim_cfg.gpu_device_id = 0
    if not hasattr(sim_cfg, "scene_id"):
        raise RuntimeError(
            "Error: Please upgrade habitat-sim. SimulatorConfig API version mismatch"
        )
    sim_cfg.scene_id = settings["scene"]

    # define default sensor parameters (see src/esp/Sensor/Sensor.h)
    sensor_specs = []

    def create_camera_spec(**kw_args):
        camera_sensor_spec = habitat_sim.CameraSensorSpec()
        for k in kw_args:
            setattr(camera_sensor_spec, k, kw_args[k])
        return camera_sensor_spec

    # TODO Figure out how to implement copying of specs
    def create_fisheye_spec(**kw_args):
        fisheye_sensor_spec = habitat_sim.FisheyeSensorDoubleSphereSpec()
        fisheye_sensor_spec.sensor_model_type = (
            habitat_sim.FisheyeSensorModelType.DOUBLE_SPHERE
        )

        # The default value (alpha, xi) is set to match the lens "GoPro" found in Table 3 of this paper:
        # Vladyslav Usenko, Nikolaus Demmel and Daniel Cremers: The Double Sphere
        # Camera Model, The International Conference on 3D Vision (3DV), 2018
        # You can find the intrinsic parameters for the other lenses in the same table as well.
        fisheye_sensor_spec.xi = -0.27
        fisheye_sensor_spec.alpha = 0.57
        fisheye_sensor_spec.focal_length = [364.84, 364.86]

        # The default principal_point_offset is the middle of the image
        fisheye_sensor_spec.principal_point_offset = None
        # default: fisheye_sensor_spec.principal_point_offset = [i/2 for i in fisheye_sensor_spec.resolution]
        for k in kw_args:
            setattr(fisheye_sensor_spec, k, kw_args[k])
        return fisheye_sensor_spec

    def create_equirect_spec(**kw_args):
        equirect_sensor_spec = habitat_sim.EquirectangularSensorSpec()
        for k in kw_args:
            setattr(equirect_sensor_spec, k, kw_args[k])
        return equirect_sensor_spec

    for sensor_cfg in settings["sensors"]:
        if sensor_cfg["camera_type"] == habitat_sim.CameraSensorSpec:
            camera_spec = create_camera_spec(
                uuid=sensor_cfg["uuid"],
                hfov=sensor_cfg["hfov"],
                sensor_type=sensor_cfg["sensor_type"],
                sensor_subtype=sensor_cfg["sensor_subtype"],
                position=sensor_cfg["position"],
                channels=sensor_cfg["channels"],
                resolution=[sensor_cfg["height"], sensor_cfg["width"]],
            )
            sensor_specs.append(camera_spec)
        elif sensor_cfg["camera_type"] == habitat_sim.FisheyeSensorDoubleSphereSpec:
            fisheye_spec = create_fisheye_spec(
                uuid=sensor_cfg["uuid"],
                hfov=sensor_cfg["hfov"],
                sensor_type=sensor_cfg["sensor_type"],
                sensor_subtype=sensor_cfg["sensor_subtype"],
                position=sensor_cfg["position"],
                channels=sensor_cfg["channels"],
                resolution=[sensor_cfg["height"], sensor_cfg["width"]],
            )
            sensor_specs.append(fisheye_spec)
        elif sensor_cfg["camera_type"] == habitat_sim.EquirectangularSensorSpec:
            equirect_spec = create_equirect_spec(
                uuid=sensor_cfg["uuid"],
                hfov=sensor_cfg["hfov"],
                sensor_type=sensor_cfg["sensor_type"],
                sensor_subtype=sensor_cfg["sensor_subtype"],
                position=sensor_cfg["position"],
                channels=sensor_cfg["channels"],
                resolution=[sensor_cfg["height"], sensor_cfg["width"]],
            )
            sensor_specs.append(equirect_spec)

    # create agent specifications
    agent_cfg = habitat_sim.agent.AgentConfiguration()
    agent_cfg.sensor_specifications = sensor_specs
    agent_cfg.action_space = {
        "move_forward": habitat_sim.agent.ActionSpec(
            "move_forward", habitat_sim.agent.ActuationSpec(amount=0.25)
        ),
        "turn_left": habitat_sim.agent.ActionSpec(
            "turn_left", habitat_sim.agent.ActuationSpec(amount=10.0)
        ),
        "turn_right": habitat_sim.agent.ActionSpec(
            "turn_right", habitat_sim.agent.ActuationSpec(amount=10.0)
        ),
    }

    return habitat_sim.Configuration(sim_cfg, [agent_cfg])
