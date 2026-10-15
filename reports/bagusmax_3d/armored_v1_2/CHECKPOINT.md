# Armored V1.2 Checkpoint

Branch: feat/bagusmax-3d-art
Current files: build_armored.py, review_armored.py; V1.2 report folder and two requested V1.2 docs. Input remains original V1.1; no candidate .blend/GLB.
Baseline hashes: preservation_before.json and asset_hashes.json.
Last passing test: actual V1.1 Khronos 0/0 and 45 independent pose evaluations; negative destination safety tests.
Last failing test: left S90/E130 local pivot/lip profile and bounded pauldron search.
Unresolved pairs: ARMOR_PAULDRON_L vs ARMOR_UPPERARM_L / FOREARM_L; ARMOR_UPPERARM_L vs ARMOR_CHEST_COLLAR; at S145/E130 UpperArm vs HELMET_EAR_L.
Next operation: prototype segmented medial cap leaf plus proximal upperarm clearance on one side, then test retained fail poses. No full rebuild.

```powershell
Set-Location E:\Projects\OpenBagus-3D
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --python tools/bagusmax_asset_pipeline/build_armored.py -- --prototype-shoulder
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --python tools/bagusmax_asset_pipeline/build_armored.py -- --solve-shoulder
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --python tools/bagusmax_asset_pipeline/build_armored.py -- --diagnose-shoulder
& 'E:\Projects\OpenBagus\.venv\Scripts\python.exe' -B tools/bagusmax_asset_pipeline/review_armored.py --revision 1.2
```
