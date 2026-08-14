/**
 * AgentMesh — a single instanced agent loaded from agent_base.glb (Module 11b, §9.1–9.2)
 *
 * One shared GLB is loaded once (useGLTF caches it). Each AgentMesh
 * clones the scene graph and overrides all materials with a wireframe
 * MeshBasicMaterial so the agent reads as a transparent, skeletal figure.
 *
 * Props:
 *   position  [x, y, z]  — world position
 *   name      string     — persona name shown as a floating label
 *   clipName  string     — animation clip to play (default "Idle")
 */

import { useRef, useEffect, useMemo } from 'react'
import { useGLTF, useAnimations, Html } from '@react-three/drei'
import { useGraph } from '@react-three/fiber'
import * as THREE from 'three'
import { SkeletonUtils } from 'three-stdlib'

const GLB_PATH = '/models/agents/agent_base.glb'

// Pre-load so the first render never stalls
useGLTF.preload(GLB_PATH)

// Wireframe material — applied to every mesh in the scene graph.
// MeshBasicMaterial ignores lighting (matches "no PBR, no gradients" rule).
const WIREFRAME_MAT = new THREE.MeshBasicMaterial({
  color: 0x2F6FED,      // --color-accent: muted blue — subtle, reads as data
  wireframe: true,
  transparent: true,
  opacity: 0.85,
})

export default function AgentMesh({ position, name, clipName = 'Idle' }) {
  const groupRef = useRef()

  // Load the shared GLB — drei caches this after the first call
  const { scene, animations } = useGLTF(GLB_PATH)

  // Clone the scene graph for this instance (skeleton + geometry, not shared)
  const clone = useMemo(() => SkeletonUtils.clone(scene), [scene])
  const { nodes } = useGraph(clone)

  // Override all meshes to wireframe
  useEffect(() => {
    clone.traverse(obj => {
      if (obj.isMesh) {
        obj.material = WIREFRAME_MAT
        obj.castShadow = false
        obj.receiveShadow = false
      }
    })
  }, [clone])

  // Set up animations on this clone's group
  const { actions, mixer } = useAnimations(animations, groupRef)

  // Play the requested clip (default: Idle)
  useEffect(() => {
    if (!actions) return
    // Stop everything, then play the target clip
    Object.values(actions).forEach(a => a?.stop())
    const target = actions[clipName] ?? actions['Idle']
    if (target) {
      target.reset().setLoop(THREE.LoopRepeat, Infinity).play()
    }
  }, [actions, clipName])

  // Label sits ~2.1 units above the root (the mesh is ~1.8 units tall at scale 1)
  const labelY = 2.3

  return (
    <group ref={groupRef} position={position}>
      <primitive object={clone} />

      {/* Floating persona name label */}
      <Html
        position={[0, labelY, 0]}
        center
        distanceFactor={14}
        zIndexRange={[5, 0]}
        occlude={false}
      >
        <div className="agent-label">{name}</div>
      </Html>
    </group>
  )
}
