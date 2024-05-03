// Copyright (c) Meta Platforms, Inc. and its affiliates.
// This source code is licensed under the MIT license found in the
// LICENSE file in the root directory of this source tree.

#include "AttributesBase.h"
#include "esp/physics/PhysicsObjectBase.h"
namespace esp {

namespace metadata {
namespace attributes {

AbstractAttributes::AbstractAttributes(const std::string& attributesClassKey,
                                       const std::string& handle)
    : Configuration() {
  // set up an existing subgroup for user_defined attributes
  addOrEditSubgroup<Configuration>("user_defined");

  init("handle", handle);
  // These fields are all hidden/internally used fields, so do not set them as
  // initialized/default values
  setClassKey(attributesClassKey);
  setID(0);
  setFileDirectory("");
  setActualFilename("");
}

}  // namespace attributes
}  // namespace metadata
}  // namespace esp
