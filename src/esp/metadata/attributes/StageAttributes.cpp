// Copyright (c) Meta Platforms, Inc. and its affiliates.
// This source code is licensed under the MIT license found in the
// LICENSE file in the root directory of this source tree.

#include "StageAttributes.h"
namespace esp {
namespace metadata {
namespace attributes {

StageAttributes::StageAttributes(const std::string& handle)
    : AbstractObjectAttributes("StageAttributes", handle) {
  init("gravity", Mn::Vector3{0, -9.8, 0});
  init("origin", Mn::Vector3{0, 0, 0});
  init("semantic_orient_up", Mn::Vector3{0, 1, 0});
  init("semantic_orient_front", Mn::Vector3{0, 0, -1});
  // Set this to true so that only used if actually changed.
  // Hidden field
  setUseFrameForAllOrientation(true);

  // setting default for semantic assets having semantically painted textures to
  // false
  init("has_semantic_textures", false);
  // TODO remove this once ShaderType support is complete
  init("force_flat_shading", true);
  // 0 corresponds to AssetType::Unknown->treated as general mesh
  init("collision_asset_type", static_cast<int>(AssetType::Unknown));
  // 4 corresponds to AssetType::InstanceMesh
  init("semantic_asset_type", static_cast<int>(AssetType::InstanceMesh));
  // set empty defaults for handles
  init("nav_asset", "");
  init("semantic_asset", "");
  init("semantic_descriptor_filename", "");
}  // StageAttributes ctor

void StageAttributes::writeValuesToJsonInternal(
    io::JsonGenericValue& jsonObj,
    io::JsonAllocator& allocator) const {
  writeValueToJson("origin", jsonObj, allocator);
  writeValueToJson("gravity", jsonObj, allocator);
  // only save values if they were actually set specifically
  if (!getUseFrameForAllOrientation()) {
    writeValueToJson("semantic_orient_up", "semantic_up", jsonObj, allocator);
    writeValueToJson("semantic_orient_front", "semantic_front", jsonObj,
                     allocator);
  }
  writeValueToJson("has_semantic_textures", jsonObj, allocator);
  writeValueToJson("semantic_asset", jsonObj, allocator);
  writeValueToJson("nav_asset", jsonObj, allocator);
  writeValueToJson("semantic_descriptor_filename", jsonObj, allocator);

}  // StageAttributes::writeValuesToJsonInternal

std::string StageAttributes::getAbstractObjectInfoHeaderInternal() const {
  std::string res = "Gravity XYZ,Origin XYZ,";
  if (!getUseFrameForAllOrientation()) {
    Cr::Utility::formatInto(res, res.length(), "{}",
                            "Semantic Up XYZ,Semantic Front XYZ,");
  }

  Cr::Utility::formatInto(
      res, res.length(), "{}",
      "Has Semantic Texture,Navmesh Handle,Semantic Asset Handle,Semantic "
      "Descriptor Filename,Light Setup,");
  return res;
}

std::string StageAttributes::getAbstractObjectInfoInternal() const {
  std::string res = Cr::Utility::formatString("{},{},", getAsString("gravity"),
                                              getAsString("origin"));

  if (!getUseFrameForAllOrientation()) {
    Cr::Utility::formatInto(res, res.length(), "{},{},",
                            getAsString("semantic_orient_up"),
                            getAsString("semantic_orient_front"));
  }
  Cr::Utility::formatInto(res, res.length(), "{},{},{},{},{}",
                          getAsString("has_semantic_textures"),
                          getNavmeshAssetHandle(), getSemanticAssetHandle(),
                          getSemanticDescriptorFilename(), getLightSetupKey());
  return res;
}

}  // namespace attributes
}  // namespace metadata
}  // namespace esp
