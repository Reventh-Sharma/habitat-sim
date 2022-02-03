// Copyright (c) Facebook, Inc. and its affiliates.
// This source code is licensed under the MIT license found in the
// LICENSE file in the root directory of this source tree.

#include "BaseMesh.h"
#include <Corrade/Utility/FormatStl.h>
#include <Magnum/Math/PackingBatch.h>
#include <Magnum/MeshTools/Compile.h>
#include "esp/scene/SemanticScene.h"

namespace Cr = Corrade;
namespace Mn = Magnum;
namespace esp {
namespace assets {

bool BaseMesh::setMeshType(SupportedMeshType type) {
  if (type < SupportedMeshType::NOT_DEFINED ||
      type >= SupportedMeshType::NUM_SUPPORTED_MESH_TYPES) {
    ESP_ERROR() << "Cannot set the mesh type to" << type;
    return false;
  }

  type_ = type;
  return true;
}

void BaseMesh::convertMeshColors(
    const Mn::Trade::MeshData& srcMeshData,
    bool convertToSRGB,
    Cr::Containers::Array<Mn::Color3ub>& meshColors) const {
  /* Assuming colors are 8-bit RGB to avoid expanding them to float and then
     packing back */
  auto colors = srcMeshData.colorsAsArray();
  if (convertToSRGB) {
    for (std::size_t i = 0; i != colors.size(); ++i) {
      meshColors[i] = colors[i].rgb().toSrgb<Mn::UnsignedByte>();
    }
  } else {
    Mn::Math::packInto(
        Cr::Containers::arrayCast<2, float>(stridedArrayView(colors))
            .except({0, 1}),
        Cr::Containers::arrayCast<2, Mn::UnsignedByte>(
            stridedArrayView(meshColors)));
  }
}  // BaseMesh::buildMeshColors

namespace {
// TODO remove when/if Magnum ever supports this function for Color3ub
constexpr const char Hex[]{"0123456789abcdef"};
}  // namespace
std::string BaseMesh::getColorAsString(Magnum::Color3ub color) const {
  char out[] = "#______";
  out[1] = Hex[(color.r() >> 4) & 0xf];
  out[2] = Hex[(color.r() >> 0) & 0xf];
  out[3] = Hex[(color.g() >> 4) & 0xf];
  out[4] = Hex[(color.g() >> 0) & 0xf];
  out[5] = Hex[(color.b() >> 4) & 0xf];
  out[6] = Hex[(color.b() >> 0) & 0xf];
  return std::string(out);
}

void BaseMesh::buildSemanticOBBs(
    const std::vector<vec3f>& vertices,
    const std::vector<uint16_t>& vertSemanticIDs,
    const std::vector<std::shared_ptr<esp::scene::SemanticObject>>& ssdObjs,
    const std::string& msgPrefix) const {
  // build per-SSD object vector of known semantic IDs
  std::size_t numSSDObjs = ssdObjs.size();
  // no semantic ID 0 so add 1 to size
  std::vector<int> semanticIDToSSOBJidx(numSSDObjs + 1);
  for (int i = 0; i < numSSDObjs; ++i) {
    const auto& ssdObj = *ssdObjs[i];
    int semanticID = ssdObj.semanticID();
    // should not happen unless semantic ids are not sequential
    if (semanticIDToSSOBJidx.size() <= semanticID) {
      semanticIDToSSOBJidx.resize(semanticID + 1);
    }
    semanticIDToSSOBJidx[semanticID] = i;
  }

  // aggegates of per-semantic ID mins and maxes
  std::vector<esp::vec3f> vertMax(
      semanticIDToSSOBJidx.size(),
      {-Mn::Constants::inf(), -Mn::Constants::inf(), -Mn::Constants::inf()});
  std::vector<esp::vec3f> vertMin(
      semanticIDToSSOBJidx.size(),
      {Mn::Constants::inf(), Mn::Constants::inf(), Mn::Constants::inf()});
  std::vector<int> vertCounts(semanticIDToSSOBJidx.size());

  // for each vertex, map vert min and max for each known semantic ID
  // Known semantic IDs are expected to be contiguous, and correspond to the
  // number of unique ssdObjs mappings.

  for (int vertIdx = 0; vertIdx < vertSemanticIDs.size(); ++vertIdx) {
    // semantic ID on vertex - valid values are 1->semanticIDToSSOBJidx.size().
    // Invalid/unknown semantic ids are > semanticIDToSSOBJidx.size()
    const auto semanticID = vertSemanticIDs[vertIdx];
    if ((semanticID > 0) && (semanticID < semanticIDToSSOBJidx.size())) {
      const auto vert = vertices[vertIdx];
      // FOR VERT-BASED OBB CALC
      // only support bbs for known colors that map to semantic objects
      vertMax[semanticID] = vertMax[semanticID].cwiseMax(vert);
      vertMin[semanticID] = vertMin[semanticID].cwiseMin(vert);
      vertCounts[semanticID] += 1;
    }
  }

  // with mins/maxs per ID, map to objs
  // give each ssdObj the values to build its OBB
  for (int semanticID = 1; semanticID < semanticIDToSSOBJidx.size();
       ++semanticID) {
    // get object with given semantic ID
    auto& ssdObj = *ssdObjs[semanticIDToSSOBJidx[semanticID]];
    esp::vec3f center{};
    esp::vec3f dims{};

    const std::string debugStr = Cr::Utility::formatString(
        "{} Semantic ID : {} : color : {} tag : {} present in {} "
        "verts | ",
        msgPrefix, semanticID,
        getColorAsString(static_cast<Mn::Color3ub>(ssdObj.getColor())),
        ssdObj.id(), vertCounts[semanticID]);
    if (vertCounts[semanticID] == 0) {
      ESP_DEBUG() << Cr::Utility::formatString(
          "{}No verts have specified Semantic ID.", debugStr);
    } else {
      center = .5f * (vertMax[semanticID] + vertMin[semanticID]);
      dims = vertMax[semanticID] - vertMin[semanticID];
      ESP_DEBUG() << Cr::Utility::formatString(
          "{}BB Center [{},{},{}] Dims [{},{},{}]", debugStr, center.x(),
          center.y(), center.z(), dims.x(), dims.y(), dims.z());
    }
    ssdObj.setObb(center, dims);
  }
}  // BaseMesh::buildSemanticOBBs

}  // namespace assets
}  // namespace esp
