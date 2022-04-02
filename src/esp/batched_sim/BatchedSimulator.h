// Copyright (c) Facebook, Inc. and its affiliates.
// This source code is licensed under the MIT license found in the
// LICENSE file in the root directory of this source tree.

#ifndef ESP_BATCHEDSIM_BATCHED_SIMULATOR_H_
#define ESP_BATCHEDSIM_BATCHED_SIMULATOR_H_

#include "esp/physics/bullet/BulletArticulatedObject.h"
#include "esp/sim/Simulator.h"
#include "esp/batched_sim/ColumnGrid.h"
#include "esp/batched_sim/BpsSceneMapping.h"
#include "esp/batched_sim/EpisodeSet.h"
#include "esp/batched_sim/SerializeCollection.h"
#include "esp/core/random.h"

#include <bps3D.hpp>

#include <thread>
#include <condition_variable>
#include <unordered_map>

namespace esp {
namespace batched_sim {

struct CameraSensorConfig {
  int width = -1;
  int height = -1;
  float hfov = -1.f;
};

struct BatchedSimulatorConfig {
  int numEnvs = -1;
  int gpuId = -1;
  bool includeDepth = true;
  bool includeColor = true;
  CameraSensorConfig sensor0;
  bool forceRandomActions = false;
  bool doAsyncPhysicsStep = false;
  int numSubsteps = 1;
  // if enabled, for every odd env, we don't render any visuals except debug stuff, 
  // e.g. collision visualization. We should keep even and odd envs in sync (e.g. same actions).
  bool doPairedDebugEnvs = false;
  bool doProceduralEpisodeSet = true;
  // only set this for doProceduralEpisodeSet==false (it is otherwise ignored)
  std::string episodeSetFilepath;
  ESP_SMART_POINTERS(BatchedSimulatorConfig);
};


struct PythonEnvironmentState {
  // curr episode
  int episode_idx = -1; // 0..len(episodes)-1
  int episode_step_idx = -1; // will be zero if this env was just reset
  int target_obj_idx = -1; // see obj_positions, obj_rotations
  // all positions/rotations are relative to the mesh, i.e. some arbitrary coordinate frame
  Magnum::Vector3 target_obj_start_pos;
  Magnum::Quaternion target_obj_start_rotation;
  Magnum::Vector3 robot_start_pos;
  Magnum::Quaternion robot_start_rotation;
  Magnum::Vector3 goal_pos;
  Magnum::Quaternion goal_rotation;

  // robot state
  Magnum::Vector3 robot_pos;
  Magnum::Quaternion robot_rotation;
  std::vector<float> robot_joint_positions;
  Magnum::Vector3 ee_pos;
  Magnum::Quaternion ee_rotation;
  bool did_collide = false;
  int held_obj_idx = -1;
  bool did_grasp = false;
  bool did_drop = false;

  // other env state
  std::vector<Magnum::Vector3> obj_positions;
  std::vector<Magnum::Quaternion> obj_rotations;

  ESP_SMART_POINTERS(PythonEnvironmentState);
};

struct BpsWrapper {
  BpsWrapper(int gpuId, int numEnvs, bool includeDepth, bool includeColor, const CameraSensorConfig& sensor0);
  ~BpsWrapper();

  std::shared_ptr<bps3D::Scene> scene_;
  std::vector<bps3D::Environment> envs_;
  std::unique_ptr<bps3D::Renderer> renderer_;
  std::unique_ptr<bps3D::AssetLoader> loader_;
};

struct Robot {
  Robot(const serialize::Collection& serializeCollection, esp::sim::Simulator* sim, BpsSceneMapping* sceneMapping);
  Robot() = default;

  void updateFromSerializeCollection(const serialize::Collection& serializeCollection);

  int numPosVars = -1;
  int numInstances_ = -1;
  int numCollisionSpheres_ = -1;

  // todo: delete artObj
  esp::physics::BulletArticulatedObject* artObj = nullptr;
  BpsSceneMapping* sceneMapping_ = nullptr;
  std::vector<Magnum::Matrix4> nodeTransformFixups;
  std::pair<std::vector<float>, std::vector<float>> jointPositionLimits;

  std::vector<std::vector<int>> collisionSpheresByNode_;
  std::vector<CollisionSphere> collisionSpheres_;

  int gripperLink_ = -1;
  Magnum::Vector3 gripperQueryOffset_; /// let's also use this as the position for the gripped obj
  float gripperQueryRadius_ = 0.f;

  std::unordered_map<std::string, int> linkIndexByName_;
  int cameraAttachNode_ = -1; // beware off-by-one with links
  Magnum::Matrix4 cameraAttachTransform_;
};

// This is misnamed and isn't actually used to store entire rollouts. It contains
// some env state. See also RobotInstance and RobotInstanceSet.
struct RolloutRecord {
  RolloutRecord() = default;
  RolloutRecord(int numRolloutSubsteps,
                int numEnvs,
                int numJointVars,
                int numNodes);

  int numRolloutSubsteps_ = 0;
  std::vector<float>
      jointPositions_;       // [numRolloutSubsteps * numEnvs * numJointVars]
  std::vector<float> yaws_;  // [numRolloutSubsteps * numEnvs]
  std::vector<Mn::Vector2> positions_;           // [numRolloutSubsteps * numEnvs]
  std::vector<Magnum::Matrix4> rootTransforms_;  // [numRolloutSubsteps * numEnvs]
  std::vector<Magnum::Matrix4>
      nodeTransforms_;  // [numRolloutSubsteps * numEnvs * numNodes]
};

// todo: move fields from RobotInstanceSet into here
class RobotInstance {
 public:
  bool doAttemptGrip_ = false;
  bool doAttemptDrop_ = false;
  // std::vector<Magnum::Vector3> grippedObjCollisionSphereWorldOrigins_;
  Magnum::Matrix4 cachedGripperLinkMat_; // sloppy: also in newNodeTransforms at glMat
  int grippedFreeObjectIndex_ = -1;
  // glm::mat4 cameraNewInvTransform_;
  Magnum::Matrix4 cameraAttachNodeTransform_;
};

class RobotInstanceSet {
 public:
  RobotInstanceSet() = default;
  RobotInstanceSet(Robot* robot,
                   const BatchedSimulatorConfig* config,
                   std::vector<bps3D::Environment>* envs,
                   RolloutRecord* rollouts);

  void applyActionPenalties(const std::vector<float>& actions);

  Robot* robot_ = nullptr;
  const BatchedSimulatorConfig* config_ = nullptr;
  RolloutRecord* rollouts_ = nullptr;

  // perf todo: try array of structs for items accessed together
  // size = num robot instances * robot num nodes (num nodes = num links + 1)
  std::vector<int> nodeInstanceIds_;
  // perf todo: try bullet aligned object array
   // size = num robot instances * robot num collision spheres
  std::vector<Mn::Vector3> collisionSphereWorldOrigins_;
  // don't try to pack this with other structs anywhere because it's int8
  std::vector<esp::batched_sim::ColumnGridSource::QueryCacheValue> collisionSphereQueryCaches_;
  // size = num robot instances * robot num instances
  std::vector<glm::mat4x3> nodeNewTransforms_;
  // size = num robot instances
  std::vector<bool> collisionResults_;
  bool areCollisionResultsValid_ = false;

  btAlignedObjectArray<btQuaternion> scratch_q_;
  btAlignedObjectArray<btVector3> scratch_m_;

  std::vector<bps3D::Environment>* envs_;

  std::vector<RobotInstance> robotInstances_;
};


class BatchedSimulator {
 public:
  BatchedSimulator(const BatchedSimulatorConfig& config);
  ~BatchedSimulator();
  void close();


  int getNumEpisodes() const;

  void startRender();
  void waitRender();

  // todo: thread-safe access to PythonEnvironmentState
  void reset(std::vector<int>&& resets);
  const std::vector<PythonEnvironmentState>& getEnvironmentStates() const;
  void startStepPhysicsOrReset(std::vector<float>&& actions, std::vector<int>&& resets);
  void waitStepPhysicsOrReset();

  bps3D::Renderer& getBpsRenderer();

  // For debugging. Sets camera for all envs.
  // todo: threadsafe or guard
  void setCamera(const Mn::Vector3& camPos, const Mn::Quaternion& camRot);
  void attachCameraToLink(const std::string& linkName, const Magnum::Matrix4& mat);

  bps3D::Environment& getBpsEnvironment(int envIndex);

  void deleteDebugInstances(); // probably call at start of frame render
  // probably add these every frame ("immediate mode", not persistent)
  // beware: probably not threadsafe
  int addDebugInstance(const std::string& name, int envIndex, 
    const Magnum::Matrix4& transform=Magnum::Matrix4(Mn::Math::IdentityInit), bool persistent=false);

  void addSphereDebugInstance(const std::string& name, int b, 
    const Magnum::Vector3& spherePos, float radius);
  void addBoxDebugInstance(const std::string& name, int b, 
    const Magnum::Vector3& pos, const Magnum::Quaternion& rotation, 
    const Magnum::Range3D& aabb, float pad=0.f, bool showBackfaces=false);

  std::string getRecentStatsAndReset() const; // todo: threadsafe

  void debugRenderColumnGrids(int b, int minProgress=0, int maxProgress=-1);

  void reloadSerializeCollection();

 private:

  struct StatRecord {
    int numSteps_ = 0;
    int numEpisodes_ = 0;
    int numStepsInCollision_ = 0;
    int numGripAttempts_ = 0;
    int numGrips_ = 0;
    int numDrops_ = 0;
    int numFailedDrops_ = 0;
  };

  void setActionsResets(std::vector<float>&& actions, std::vector<int>&& resets);
  void stepPhysics();
  void substepPhysics();
  void updateLinkTransforms(int currRolloutSubstep, bool updateforPhysics, bool updateForRender, bool includeResettingEnvs);
  void updateCollision();
  // for each robot, undo action if collision
  void postCollisionUpdate();
  // update robot link instances
  void updateRenderInstances(bool forceUpdate);
  void reverseActionsForEnvironment(int b);
  void updateGripping();
  void resetHelper();
  void updatePythonEnvironmentState();

  // uses episode spawn location
  void spawnFreeObject(int b, int freeObjectIndex, bool reinsert);
  // remember to update your bps instance after calling this!
  void removeFreeObjectFromCollisionGrid(int b, int freeObjectIndex);
  void reinsertFreeObject(int b, int freeObjectIndex,
    const Magnum::Vector3& pos, const Magnum::Quaternion& rotation);

  void initEpisodeSet();
  void initEpisodeInstances();
  void clearEpisodeInstance(int b);
  void resetEpisodeInstance(int b); // uses resets_[b]
  bool isEnvResetting(int b) const;

  void physicsThreadFunc(int startEnvIndex, int numEnvs);
  void signalStepPhysics();
  void signalKillPhysicsThread();

  int getFreeObjectBpsInstanceId(int b, int freeObjectIndex) const;
  Magnum::Matrix4 getHeldObjectTransform(int b) const;

  bool isPhysicsThreadActive() const;

  BatchedSimulatorConfig config_;
  serialize::Collection serializeCollection_;
  bool isOkToRender_ = false;
  bool isOkToStep_ = false;
  bool isRenderStarted_ = false;
  Robot robot_;
  RobotInstanceSet robots_;
  int currStorageStep_ = -1;
  int prevStorageStep_ = -1;
  int substep_ = -1;
  RolloutRecord rollouts_;
  std::unique_ptr<esp::sim::Simulator> legacySim_;
  std::unique_ptr<BpsWrapper> bpsWrapper_;
  int actionDim_ = -1;
  std::vector<float> actions_;
  std::vector<int> resets_; // episode index, or -1 if not resetting
  int maxStorageSteps_ = -1;
  std::vector<PythonEnvironmentState> pythonEnvStates_;

  EpisodeSet episodeSet_;
  EpisodeInstanceSet episodeInstanceSet_;

  BpsSceneMapping sceneMapping_;
  std::vector<std::vector<int>> debugInstancesByEnv_;
  mutable StatRecord recentStats_;
  esp::core::Random random_{0};

  std::thread physicsThread_;
  std::mutex physicsSignalMutex_;
  std::mutex physicsFinishMutex_;
  std::condition_variable physicsCondVar_; 
  bool signalStepPhysics_ = false;
  bool signalKillPhysicsThread_ = false;
  bool isStepPhysicsOrResetFinished_ = true;
  bool areRenderInstancesUpdated_ = false;

  ESP_SMART_POINTERS(BatchedSimulator)
};

}  // namespace batched_sim
}  // namespace esp

#endif
