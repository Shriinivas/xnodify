import bpy
import sys

def debug():
    print("Debugging bpy.types...")
    
    # Check specific known node
    if hasattr(bpy.types, 'ShaderNodeMath'):
        print("ShaderNodeMath found in bpy.types")
        cls = bpy.types.ShaderNodeMath
        print(f"bl_idname: {getattr(cls, 'bl_idname', 'None')}")
    else:
        print("ShaderNodeMath NOT found in bpy.types")
        
    # List some GeometryNodes
    count = 0
    for name in dir(bpy.types):
        if 'GeometryNode' in name:
            print(f"Found type: {name}")
            cls = getattr(bpy.types, name)
            print(f"  bl_idname: {getattr(cls, 'bl_idname', 'None')}")
            count += 1
            if count > 5:
                break
                
    print(f"Total items in bpy.types: {len(dir(bpy.types))}")

if __name__ == "__main__":
    debug()
