// Copyright (c) Facebook, Inc. and its affiliates.
// This source code is licensed under the MIT license found in the
// LICENSE file in the root directory of this source tree.

#include "esp/batched_sim/ColumnGrid.h"
#include "esp/batched_sim/GlmUtils.h"
#include "esp/core/logging.h"

#include <Corrade/TestSuite/Compare/Numeric.h>
#include <Corrade/TestSuite/Tester.h>
#include <Corrade/Utility/Directory.h>

#include <Magnum/Magnum.h>
#include <Magnum/Math/Quaternion.h>
#include <Magnum/Math/Vector3.h>
#include <Magnum/Math/Matrix4.h>
#include <Magnum/Math/Range.h>

#include <glm/gtx/transform.hpp>

using esp::batched_sim::ColumnGridSource;
namespace Cr = Corrade;
namespace Mn = Magnum;

namespace {

struct ColumnGridTest : Cr::TestSuite::Tester {
  explicit ColumnGridTest();

  void testBasic();
  void testSaveLoad();

  // todo: consolidate all BatchedSim tests to one file?
  void testInverseTransformPoint();
  void testSphereBoxContactTest();

  void batchSphereOrientedBoxContactTest();

  esp::logging::LoggingContext loggingContext;

};  // struct ColumnGridTest

ColumnGridTest::ColumnGridTest() {
  addTests({&ColumnGridTest::testBasic,
    &ColumnGridTest::batchSphereOrientedBoxContactTest,
    &ColumnGridTest::testSaveLoad,
    &ColumnGridTest::testInverseTransformPoint,
    &ColumnGridTest::testSphereBoxContactTest
  });
}  // ctor


void ColumnGridTest::testBasic() {

  ColumnGridSource source;

  // todo: force these in constructor
  source.minX = 0.f;
  source.minZ = 0.f;
  source.dimX = 100;
  source.dimZ = 100;
  source.gridSpacing = 1.f;
  source.invGridSpacing = 1.f / source.gridSpacing;
  constexpr float sphereRadius = 1.f;
  source.sphereRadius = sphereRadius;

  ColumnGridSource::QueryCacheValue queryCache = 0;

  CORRADE_COMPARE(source.contactTest({0.5, 0.5, 0.5}, &queryCache), true); // empty grid (no free space)

  source.appendColumn(0, 0, 1.f, 2.f);

  constexpr float eps = 0.001f;
  CORRADE_COMPARE(source.contactTest({0.5, 1.f - eps, 0.5}, &queryCache), true); // slightly below
  CORRADE_COMPARE(queryCache, 0);
  CORRADE_COMPARE(source.contactTest({0.5, 1.f - sphereRadius * 2.f, 0.5}, &queryCache), true); // far below
  CORRADE_COMPARE(source.contactTest({0.5, 2.f + eps, 0.5}, &queryCache), true); // slightly above
  CORRADE_COMPARE(source.contactTest({0.5, 2.f + sphereRadius * 2.f, 0.5}, &queryCache), true); // far above

  CORRADE_COMPARE(source.contactTest({0.f - eps, 1.5, 0.5}, &queryCache), true); // slightly left
  CORRADE_COMPARE(source.contactTest({source.dimX + eps, 1.5, 0.5}, &queryCache), true); // slightly right
  CORRADE_COMPARE(source.contactTest({0.5, 1.5, 0.f - eps}, &queryCache), true); // slightly behind
  CORRADE_COMPARE(source.contactTest({0.5, 1.5, source.dimZ + eps}, &queryCache), true); // slightly forward

  CORRADE_COMPARE(source.contactTest({0.5, 1.5, 0.5}, &queryCache), false);
  CORRADE_COMPARE(queryCache, 0);

  // add two more free columns
  source.appendColumn(0, 0, 3.f, 4.f);
  source.appendColumn(0, 0, 5.f, 6.f);

  for (ColumnGridSource::QueryCacheValue queryCache : {-1, 0, 1, 2, 3}) {
    CORRADE_COMPARE(source.contactTest({0.5, 2.5, 0.5}, &queryCache), true); // middle, in collision
  }

  for (ColumnGridSource::QueryCacheValue queryCache : {-1, 0, 1, 2, 3}) {
    CORRADE_COMPARE(source.contactTest({0.5, 1.5, 0.5}, &queryCache), false); // free, layer 0
    CORRADE_COMPARE(queryCache, 0);
  }

  for (ColumnGridSource::QueryCacheValue queryCache : {-1, 0, 1, 2, 3}) {
    CORRADE_COMPARE(source.contactTest({0.5, 3.5, 0.5}, &queryCache), false); // free, layer 1
    CORRADE_COMPARE(queryCache, 1);
  }

  for (ColumnGridSource::QueryCacheValue queryCache : {-1, 0, 1, 2, 3}) {
    CORRADE_COMPARE(source.contactTest({0.5, 5.5, 0.5}, &queryCache), false); // free, layer 2
    CORRADE_COMPARE(queryCache, 2);
  }

  source.appendColumn(99, 0, 7.f, 8.f);
  source.appendColumn(0, 99, 9.f, 10.f);
  source.appendColumn(99, 99, 11.f, 12.f);

  CORRADE_COMPARE(source.contactTest({99.5, 7.5, 0.5}, &queryCache), false);
  CORRADE_COMPARE(source.contactTest({99.5, 9.5, 0.5}, &queryCache), true);
  CORRADE_COMPARE(source.contactTest({99.5, 11.5, 0.5}, &queryCache), true);

  CORRADE_COMPARE(source.contactTest({0.5, 7.5, 99.5}, &queryCache), true);
  CORRADE_COMPARE(source.contactTest({0.5, 9.5, 99.5}, &queryCache), false);
  CORRADE_COMPARE(source.contactTest({0.5, 11.5, 99.5}, &queryCache), true);

  CORRADE_COMPARE(source.contactTest({99.5, 7.5, 99.5}, &queryCache), true);
  CORRADE_COMPARE(source.contactTest({99.5, 9.5, 99.5}, &queryCache), true);
  CORRADE_COMPARE(source.contactTest({99.5, 11.5, 99.5}, &queryCache), false);

}


void ColumnGridTest::testSaveLoad() {

  ColumnGridSource source;

  source.minX = 1.f;
  source.minZ = 2.f;
  source.dimX = 3;
  source.dimZ = 4;
  source.gridSpacing = 5.f;
  source.invGridSpacing = 1.f / source.gridSpacing;
  source.sphereRadius = 6.f;

  int counter = 0;
  for (int cellX = 0; cellX < source.dimX; cellX++) {
    for (int cellZ = 0; cellZ < source.dimZ; cellZ++) {
      int numColumns = (counter++ % 10);
      for (int i = 0; i < numColumns; i++) {
        float a = float(counter++);
        float b = float(counter++);
        source.appendColumn(cellX, cellZ, a, b);
      }
    }
  }

  const std::string filepath = "./temp.columngrid";
  source.save(filepath);

  ColumnGridSource source2;
  source2.load(filepath);

  CORRADE_COMPARE(source.minX, source2.minX);
  CORRADE_COMPARE(source.minZ, source2.minZ);
  CORRADE_COMPARE(source.dimX, source2.dimX);
  CORRADE_COMPARE(source.dimZ, source2.dimZ);
  CORRADE_COMPARE(source.gridSpacing, source2.gridSpacing);
  CORRADE_COMPARE(source.invGridSpacing, source.invGridSpacing);
  CORRADE_COMPARE(source.sphereRadius, source.sphereRadius);
  CORRADE_VERIFY(source.patches.size() == source.patches.size());
  CORRADE_VERIFY(source.layers == source.layers);

  bool success = Corrade::Utility::Directory::rm(filepath);
  if (!success) {
    ESP_WARNING() << "Unable to remove temporary test JSON file"
                  << filepath;
  }

}

void ColumnGridTest::testInverseTransformPoint() {

  Mn::Vector3 pos(1.f, 2.f, 3.f);

  auto rot = Mn::Quaternion::rotation(Mn::Deg(35.f), Mn::Vector3(-1.f, 2.f, -3.f).normalized());
  Mn::Vector3 matTranslation(0.f, 10.f, 100.f);
  // todo: add scale
  Mn::Matrix4 mat = Mn::Matrix4::from(
      rot.toMatrix(), matTranslation);

  Mn::Vector3 transformedPos = mat.transformPoint(pos);

  glm::mat4x3 glMat = esp::batched_sim::toGlmMat4x3(mat);

  Mn::Vector3 pos2 = esp::batched_sim::inverseTransformPoint(glMat, transformedPos);

  constexpr float eps = 0.0001f;
  CORRADE_VERIFY((pos2 - pos).length() < eps);
}

void ColumnGridTest::testSphereBoxContactTest() {

  Mn::Range3D box({-1.f, -12.f, -130.f}, {2.f, 13.f, 140.f});

  constexpr float eps = 0.001f;
  CORRADE_VERIFY(esp::batched_sim::sphereBoxContactTest({-2.f, 0.f, 0.f}, 1.f - eps, box) == false);
  CORRADE_VERIFY(esp::batched_sim::sphereBoxContactTest({-2.f, 0.f, 0.f}, 1.f + eps, box) == true);
  CORRADE_VERIFY(esp::batched_sim::sphereBoxContactTest({3.f, 0.f, 0.f}, 1.f - eps, box) == false);
  CORRADE_VERIFY(esp::batched_sim::sphereBoxContactTest({3.f, 0.f, 0.f}, 1.f + eps, box) == true);

  CORRADE_VERIFY(esp::batched_sim::sphereBoxContactTest({0.f, -13.f, 0.f}, 1.f - eps, box) == false);
  CORRADE_VERIFY(esp::batched_sim::sphereBoxContactTest({0.f, -13.f, 0.f}, 1.f + eps, box) == true);
  CORRADE_VERIFY(esp::batched_sim::sphereBoxContactTest({0.f, 14.f, 0.f}, 1.f - eps, box) == false);
  CORRADE_VERIFY(esp::batched_sim::sphereBoxContactTest({0.f, 14.f, 0.f}, 1.f + eps, box) == true);

  CORRADE_VERIFY(esp::batched_sim::sphereBoxContactTest({0.f, 0.f, -131.f}, 1.f - eps, box) == false);
  CORRADE_VERIFY(esp::batched_sim::sphereBoxContactTest({0.f, 0.f, -131.f}, 1.f + eps, box) == true);
  CORRADE_VERIFY(esp::batched_sim::sphereBoxContactTest({0.f, 0.f, 141.f}, 1.f - eps, box) == false);
  CORRADE_VERIFY(esp::batched_sim::sphereBoxContactTest({0.f, 0.f, 141.f}, 1.f + eps, box) == true);

  CORRADE_VERIFY(esp::batched_sim::sphereBoxContactTest({2.8, 13.8f, 0.f}, 1.f, box) == false);
  CORRADE_VERIFY(esp::batched_sim::sphereBoxContactTest({2.7, 13.7f, 0.f}, 1.f, box) == true);

  CORRADE_VERIFY(esp::batched_sim::sphereBoxContactTest({-1.8, 0.f, -130.8f}, 1.f, box) == false);
  CORRADE_VERIFY(esp::batched_sim::sphereBoxContactTest({-1.7, 0.f,   140.7}, 1.f, box) == true);

}

void ColumnGridTest::batchSphereOrientedBoxContactTest() {

  std::vector<Magnum::Vector3> spherePositionsStorage;
  std::vector<Magnum::Range3D> boxRangesStorage;

  constexpr glm::mat4x3 identityGlMat = glm::mat4x3(
    1.f, 0.f, 0.f,
    0.f, 1.f, 0.f,
    0.f, 0.f, 1.f, 
    0.f, 0.f, 0.f);

  constexpr int contactTestBatchSize = 64;
  std::array<const glm::mat4x3*, contactTestBatchSize> orientedBoxTransforms;
  std::array<const Magnum::Vector3*, contactTestBatchSize> spherePositions;
  std::array<const Magnum::Range3D*, contactTestBatchSize> boxRanges;

  for (int i = 0; i < contactTestBatchSize; i++) {

    orientedBoxTransforms[i] = &identityGlMat;

    spherePositionsStorage.push_back(Mn::Vector3(
      (float)i * 3.f + 0,
      (float)i * 3.f + 1,
      (float)i * 3.f + 2));
    spherePositions[i] = &spherePositionsStorage[i];

    boxRangesStorage.push_back(Mn::Range3D(
      Mn::Vector3(
        -(100.f + (float)i * 3.f + 0),
        -(100.f + (float)i * 3.f + 1),
        -(100.f + (float)i * 3.f + 2)),
      Mn::Vector3(
        (200.f + (float)i * 3.f + 0),
        (200.f + (float)i * 3.f + 1),
        (200.f + (float)i * 3.f + 2))));
    boxRanges[i] = &boxRangesStorage[i];
  }

  constexpr int numCollectedTests = 64;
  constexpr float sphereRadiusSq = 0.1f * 0.1f;
  esp::batched_sim::batchSphereOrientedBoxContactTest<contactTestBatchSize, true>(
    &orientedBoxTransforms[0],
    &spherePositions[0], sphereRadiusSq, &boxRanges[0], numCollectedTests);  

}

}

CORRADE_TEST_MAIN(ColumnGridTest)