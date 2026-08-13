"""
Blender batch script: combine Mixamo base character + 4 animation clips
into one agent_base.glb for EcoSim-MAS module 10/11.

Run headless:
  /Applications/Blender.app/Contents/MacOS/Blender --background --python scripts/convert_agent.py
"""
import bpy
import os

EXPORT_DIR = os.path.expanduser("~/ecosim-mas/mixamo-exports/agent_base")
OUTPUT_PATH = os.path.expanduser("~/ecosim-mas/frontend/public/models/agents/agent_base.glb")

# Start from a clean, empty scene
bpy.ops.wm.read_factory_settings(use_empty=True)

# 1. Import the base character (with skin — mesh + skeleton)
bpy.ops.import_scene.gltf(filepath=os.path.join(EXPORT_DIR, "character_test.glb"))

base_armature = next(
    (obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"), None
)
if base_armature is None:
    raise RuntimeError("No armature found in character.fbx — check the base download.")

# 2. Import each animation-only FBX, steal its action, discard the rest
animations = {
    "Idle":     "Idle.fbx",
    "Walk":     "Walking.fbx",
    "Sit":      "Sitting.fbx",
    "Defeated": "Defeated.fbx",
}

for clip_name, filename in animations.items():
    before = set(bpy.context.scene.objects)
    bpy.ops.import_scene.fbx(filepath=os.path.join(EXPORT_DIR, filename))
    new_objs = set(bpy.context.scene.objects) - before

    anim_armature = next((o for o in new_objs if o.type == "ARMATURE"), None)
    if anim_armature and anim_armature.animation_data and anim_armature.animation_data.action:
        action = anim_armature.animation_data.action
        action.name = clip_name
        action.use_fake_user = True  # keep it alive after we delete the source object

    for obj in new_objs:
        bpy.data.objects.remove(obj, do_unlink=True)

# 3. Push each captured action onto its own NLA track on the base armature
#    so the glTF exporter treats them as separate, selectable animation clips
if not base_armature.animation_data:
    base_armature.animation_data_create()

for clip_name in animations:
    action = bpy.data.actions.get(clip_name)
    if action:
        track = base_armature.animation_data.nla_tracks.new()
        track.name = clip_name
        track.strips.new(clip_name, int(action.frame_range[0]), action)

# 4. Select the armature + its mesh, export as one .glb
os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
bpy.ops.object.select_all(action="DESELECT")
base_armature.select_set(True)
for child in base_armature.children:
    child.select_set(True)

bpy.ops.export_scene.gltf(
    filepath=OUTPUT_PATH,
    export_format="GLB",
    use_selection=True,
    export_animations=True,
    export_nla_strips=True,
)

print(f"Export complete: {OUTPUT_PATH}")
