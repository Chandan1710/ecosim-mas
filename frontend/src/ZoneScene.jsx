/**
 * ZoneScene — static 3D environment (Module 11a, §9.1)
 *
 * Six fixed zone buildings on a flat ground plane.
 * No agents, no WebSocket — purely the static world geometry.
 *
 * Design constraints (§9.4):
 *   - Flat shaded, no PBR maps, no gradients
 *   - Zone colours from CSS design system (replicated here as Three.js hex values)
 *   - Camera: isometric-style OrbitControls, restricted polar angle
 */

import { useRef } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls, Html } from '@react-three/drei'
import * as THREE from 'three'

// ── Zone definitions ───────────────────────────────────────────────────────
// Positions keep zones at least 8 units apart on the XZ plane.
// Y is always 0 (ground level for the base of each building).

const ZONES = [
  {
    id: 'home',
    label: 'Home',
    position: [-14, 0, -8],
    color: 0x8B9E7E,   // muted sage green
    roofColor: 0x6E8063,
    width: 3.5, depth: 3.5, wallHeight: 2.2,
  },
  {
    id: 'workplace',
    label: 'Workplace',
    position: [0, 0, -14],
    color: 0x7B8FA6,   // slate blue
    roofColor: 0x5C7189,
    width: 5, depth: 4, wallHeight: 4.5,   // taller office block
  },
  {
    id: 'mall',
    label: 'Mall',
    position: [14, 0, -4],
    color: 0xC4956A,   // warm terracotta
    roofColor: 0xA07550,
    width: 6, depth: 5, wallHeight: 3.0,   // wide low-rise
  },
  {
    id: 'cafe',
    label: 'Café',
    position: [10, 0, 10],
    color: 0xA67B5B,   // espresso brown
    roofColor: 0x7D5A3E,
    width: 3, depth: 3, wallHeight: 2.0,
  },
  {
    id: 'theater',
    label: 'Theater',
    position: [-6, 0, 12],
    color: 0x6A7B9E,   // dusty indigo
    roofColor: 0x4E5F80,
    width: 5.5, depth: 4.5, wallHeight: 3.5,
  },
  {
    id: 'grocery',
    label: 'Grocery',
    position: [-16, 0, 6],
    color: 0x7E9E8B,   // cool mint
    roofColor: 0x608070,
    width: 4, depth: 3.5, wallHeight: 2.5,
  },
]

// ── Building component ──────────────────────────────────────────────────────

function Building({ zone }) {
  const { position, color, roofColor, width, depth, wallHeight, label } = zone

  // Wall material — flat shaded, no PBR
  const wallMat = new THREE.MeshLambertMaterial({ color, flatShading: true })
  // Roof material
  const roofMat = new THREE.MeshLambertMaterial({ color: roofColor, flatShading: true })

  const wallY   = wallHeight / 2          // center Y of the wall box
  const roofY   = wallHeight + 0.85       // apex of the roof cone

  // Roof is a ConeGeometry — minimal triangles, clearly reads as a building
  const roofRadiusBase = Math.max(width, depth) * 0.72
  const roofHeight     = 1.7

  // Label sits above the roof
  const labelY = wallHeight + roofHeight + 0.8

  return (
    <group position={position}>
      {/* Walls */}
      <mesh position={[0, wallY, 0]} material={wallMat} castShadow={false}>
        <boxGeometry args={[width, wallHeight, depth]} />
      </mesh>

      {/* Roof */}
      <mesh position={[0, roofY, 0]} material={roofMat}>
        <coneGeometry args={[roofRadiusBase, roofHeight, 4, 1]} />
      </mesh>

      {/* Zone label — rendered as HTML overlay via drei's Html */}
      <Html
        position={[0, labelY, 0]}
        center
        distanceFactor={18}
        zIndexRange={[10, 0]}
      >
        <div className="zone-label">{label}</div>
      </Html>
    </group>
  )
}

// ── Ground plane ────────────────────────────────────────────────────────────

function Ground() {
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.01, 0]} receiveShadow={false}>
      <planeGeometry args={[80, 80]} />
      <meshLambertMaterial color={0xD9D6CE} flatShading={true} />
    </mesh>
  )
}

// ── Scene lighting — no gradients, no coloured fills ─────────────────────

function SceneLighting() {
  return (
    <>
      {/*
        Flat, neutral ambient — matches "no gradients" design rule.
        A single DirectionalLight provides enough depth cues without
        dramatic shadows or colour tinting.
      */}
      <ambientLight intensity={1.6} color={0xFFFFFF} />
      <directionalLight
        position={[20, 30, 20]}
        intensity={0.9}
        color={0xFFFFFF}
      />
    </>
  )
}

// ── Camera helpers ──────────────────────────────────────────────────────────

const CAMERA_POSITION = [28, 28, 28]   // isometric-ish starting angle

function SceneCamera() {
  return (
    <OrbitControls
      enablePan={true}
      enableZoom={true}
      enableRotate={true}
      minPolarAngle={Math.PI / 8}       // can't go past bird's-eye
      maxPolarAngle={Math.PI / 2.4}     // can't go below horizon
      minDistance={10}
      maxDistance={80}
      target={[0, 0, 0]}
    />
  )
}

// ── Root export ─────────────────────────────────────────────────────────────

export default function ZoneScene() {
  return (
    <Canvas
      camera={{ position: CAMERA_POSITION, fov: 40, near: 0.1, far: 500 }}
      style={{ background: '#EFF0F2' }}   // --color-sky from design system
      gl={{ antialias: true }}
    >
      <SceneLighting />
      <Ground />
      {ZONES.map(zone => (
        <Building key={zone.id} zone={zone} />
      ))}
      <SceneCamera />
    </Canvas>
  )
}
