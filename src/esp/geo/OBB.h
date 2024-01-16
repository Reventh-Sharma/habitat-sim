// Copyright (c) Meta Platforms, Inc. and its affiliates.
// This source code is licensed under the MIT license found in the
// LICENSE file in the root directory of this source tree.

#ifndef ESP_GEO_OBB_H_
#define ESP_GEO_OBB_H_

#include <Magnum/Math/Quaternion.h>
#include "esp/core/Esp.h"
#include "esp/geo/Geo.h"

namespace esp {
namespace geo {

// oriented bounding box
class OBB {
 public:
  explicit OBB();
  explicit OBB(const Mn::Vector3& center,
               const Mn::Vector3& dimensions,
               const Mn::Quaternion& rotation);
  explicit OBB(const box3f& aabb);

  //! Returns centroid of this OBB
  Mn::Vector3 center() const { return center_; }

  //! Returns the dimensions of this OBB in its own frame of reference
  Mn::Vector3 sizes() const { return halfExtents_ * 2; }

  /**
   * @brief Return the volume of this bbox
   */
  float volume() const {
    return halfExtents_.x() * halfExtents_.y() * halfExtents_.z() * 8.0f;
  }

  //! Returns half-extents of this OBB (dimensions)
  Mn::Vector3 halfExtents() const { return halfExtents_; }

  //! Returns quaternion representing rotation of this OBB
  Mn::Quaternion rotation() const { return rotation_; }

  //! Return Transform from world coordinates to local [0,1]^3 coordinates
  const Transform& worldToLocal() const { return worldToLocal_; }

  //! Return Transform from local [0,1]^3 coordinates to world coordinates
  const Transform& localToWorld() const { return localToWorld_; }

  //! Returns an axis aligned bounding box bounding this OBB
  box3f toAABB() const;

  //! Returns distance to p from closest point on OBB surface
  //! (0 if point p is inside box)
  float distance(const Mn::Vector3& p) const;

  //! Return closest point to p within OBB.  If p is inside return p.
  Mn::Vector3 closestPoint(const Mn::Vector3& p) const;

  //! Returns whether world coordinate point p is contained in this OBB within
  //! threshold distance epsilon
  bool contains(const Mn::Vector3& p, float epsilon = 1e-6f) const;

  //! Rotate this OBB by the given rotation and return reference to self
  OBB& rotate(const Mn::Quaternion& rotation);

 protected:
  void recomputeTransforms();

  Mn::Vector3 center_;
  Mn::Vector3 halfExtents_;
  Mn::Quaternion rotation_;
  Transform localToWorld_, worldToLocal_;
  ESP_SMART_POINTERS(OBB)
};

inline std::ostream& operator<<(std::ostream& os, const OBB& obb) {
  return os << "{c:" << obb.center() << ",h:" << obb.halfExtents()
            << ",r:" << obb.rotation().coeffs() << "}";
}

// compute a minimum area OBB containing given points, and constrained to
// have -Z axis along given gravity orientation
OBB computeGravityAlignedMOBB(const Mn::Vector3& gravity,
                              const std::vector<Mn::Vector3>& points);

}  // namespace geo
}  // namespace esp

#endif  // ESP_GEO_OBB_H_
