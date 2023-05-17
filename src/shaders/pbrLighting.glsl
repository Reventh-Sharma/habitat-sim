// Copyright (c) Meta Platforms, Inc. and its affiliates.
// This source code is licensed under the MIT license found in the
// LICENSE file in the root directory of this source tree.

precision highp float;


// TODO : make exposure a uniform?
const highp float exposure = 4.5f;
// TODO : make gamma a uniform?
const float gamma = 2.2f;

const float invGamma = 1.0f/gamma;

#if (LIGHT_COUNT > 0)
// -------------- lights -------------------
// NOTE: In this shader, the light intensity is considered in the lightColor!!
uniform vec3 LightColors[LIGHT_COUNT];
uniform float LightRanges[LIGHT_COUNT];

// lights in world space!
// if .w == 0, it means it is a directional light, .xyz is the direction;
// if .w == 1, it means it is a point light, .xyz is the light position;
// it is NOT put in the Light Structure, simply because we may modify the code
// so it is computed in the vertex shader.
uniform vec4 LightDirections[LIGHT_COUNT];
#endif


/////////////////
//IBL Support
#if defined(IMAGE_BASED_LIGHTING)
uniform samplerCube IrradianceMap;
uniform sampler2D BrdfLUT;
uniform samplerCube PrefilteredMap;
#endif


// scales for components in the PBR equation
// [0] = direct diffuse
// [1] = direct specular
// [2] = ibl diffuse
// [3] = ibl specular

#if defined(IMAGE_BASED_LIGHTING) && (LIGHT_COUNT > 0)
const int DirectDiffuse = 0;
const int DirectSpecular = 1;
const int IblDiffuse = 2;
const int IblSpecular = 3;
uniform highp vec4 ComponentScales;
#endif

#if defined(IMAGE_BASED_LIGHTING)
uniform uint PrefilteredMapMipLevels;
#endif


// The following function Uncharted2Tonemap is based on:
// https://github.com/SaschaWillems/Vulkan-glTF-PBR/blob/master/data/shaders/pbr_khr.frag
vec3 Uncharted2Tonemap(vec3 color) {
  float A = 0.15;
  float B = 0.50;
  float C = 0.10;
  float D = 0.20;
  float E = 0.02;
  float F = 0.30;
  float W = 11.2;
  return ((color * (A * color + C * B) + D * E) /
          (color * (A * color + B) + D * F)) -
         E / F;
}

// The following function tonemap is based on:
// https://github.com/SaschaWillems/Vulkan-glTF-PBR/blob/master/data/shaders/pbr_khr.frag
// Tone mapping is to take a wide dynamic range of values and compressing them
// into a smaller range that is appropriate for the output device.
vec4 tonemap(vec4 color) {
#ifdef TONE_MAP
  vec3 outcol = Uncharted2Tonemap(color.rgb * exposure);
  outcol = outcol * (1.0f / Uncharted2Tonemap(vec3(11.2f)));
  return vec4(pow(outcol, vec3(invGamma)), color.a);
#else
  return color;
#endif
}



#if defined(IMAGE_BASED_LIGHTING)
// diffuseColor: diffuse color
// n: normal on shading location in world space
vec3 computeIBLDiffuse(vec3 diffuseColor, vec3 n) {
  // diffuse part = diffuseColor * irradiance
  // return diffuseColor * texture(IrradianceMap, n).rgb * Scales.iblDiffuse;
  return diffuseColor * tonemap(texture(IrradianceMap, n)).rgb;
}

vec3 computeIBLSpecular(float roughness,
                        float n_dot_v,
                        vec3 specularReflectance,
                        vec3 reflectionDir) {
  vec3 brdf = texture(BrdfLUT, vec2(n_dot_v, roughness)).rgb;
  float lod = roughness * float(PrefilteredMapMipLevels-1);
  vec3 prefilteredColor =
      tonemap(textureLod(PrefilteredMap, reflectionDir, lod)).rgb;

  return prefilteredColor * (specularReflectance * brdf.x + brdf.y);
}
#endif // IMAGE_BASED_LIGHTING
