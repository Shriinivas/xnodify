#
# This Blender add-on arranges nodes within node editor windows of geometry
# nodes, shader nodes and compositor nodes
#
# Copyright (C) 2022  Shrinivas Kulkarni
#
# License: GPL3 (https://github.com/Shriinivas/lineupnodes/blob/main/LICENSE)
#
# NOTE: This file is maintained in two repositories:
#   1) Standalone Addon:  /home/khemadeva/hari/dev/code/remotegits/lineupnodes/lineupnodes.py
#   2) Bundled in XNodify: /home/khemadeva/hari/dev/code/remotegits/xnodify/lineupnodes.py
# If modifying one, keep both in sync (use `python3 tools/sync_lineupnodes.py` from xnodify).
#

import bpy
from bpy.types import PropertyGroup, Operator, Panel
from bpy.props import EnumProperty, IntProperty, BoolProperty

bl_info = {
    "name": "Line Up Nodes",
    "author": "Shrinivas Kulkarni",
    "version": (1, 0),
    "blender": (2, 80, 0),
    "location": "Shader/Geometry/Compositor Node Editor > Sidebar > Edit Tab",
    "description": "Line up nodes",
    "category": "Object",
}


class SrcLinkInfo:
    def __init__(self):
        self.linkCntMap = {}

        # For arrangeType MAX
        self.maxLinkCnt = 0
        self.maxLinkNode = 0

        # For arrangeType FIRST and LAST
        self.row = None
        self.column = None

    def addLinkCnt(self, destNode):
        if self.linkCntMap.get(destNode) is None:
            self.linkCntMap[destNode] = 0
        self.linkCntMap[destNode] += 1

        if self.linkCntMap[destNode] > self.maxLinkCnt:
            self.maxLinkCnt = self.linkCntMap[destNode]
            self.maxLinkNode = destNode

    def removeDestNode(self, destNode):
        if self.linkCntMap.get(destNode) is not None:
            return self.linkCntMap.pop(destNode)

    def getLinkNodeCnt(self):
        return len(self.linkCntMap)

    def __repr__(self):
        return (
            f"[[{self.maxLinkCnt}->{self.maxLinkNode.name}--"
            + str({k.name: self.linkCntMap[k] for k in self.linkCntMap})
            + "]]"
        )


def getActiveNodeTree(context):
    obj = context.active_object
    uitype = context.area.ui_type
    nodeTree = None
    if uitype == "ShaderNodeTree":
        return obj.active_material.node_tree
    elif uitype == "GeometryNodeTree":
        return obj.modifiers.active.node_group
    elif uitype == "CompositorNodeTree":
        return context.scene.node_tree
    return nodeTree


def processNodes(
    srcNodeMap, nodeGraph, nodeTree, destNode, srcNodes, depth, arrangeType, maxColNodes
):
    if len(nodeGraph) <= depth:
        nodeGraph.extend([[] for _ in range(depth - len(nodeGraph) + 1)])

    for node in srcNodes:
        if depth == 0:
            curDepth = 0
            if maxColNodes > 0:
                while curDepth < len(nodeGraph) and len(nodeGraph[curDepth]) >= maxColNodes:
                    curDepth += 1
            while len(nodeGraph) <= curDepth:
                nodeGraph.append([])
            nodeGraph[curDepth].append(node)
            srcs = {k.from_node for k in nodeTree.links if k.to_node == node}
            processNodes(
                srcNodeMap,
                nodeGraph,
                nodeTree,
                node,
                srcs,
                curDepth + 1,
                arrangeType,
                maxColNodes,
            )
        else:
            srcLinkInfo = srcNodeMap.get(node)
            if srcLinkInfo is None:  # Already processed
                continue
            elif arrangeType == "MAX":
                if srcLinkInfo.maxLinkNode == destNode:
                    srcNodeMap.pop(node)
                else:
                    continue
            elif arrangeType == "FIRST":
                if srcLinkInfo.column is not None:
                    continue
                srcLinkInfo.column = depth
            else:  # arrangeType == "LAST"
                srcLinkInfo.removeDestNode(destNode)
                if srcLinkInfo.column is None or depth > srcLinkInfo.column:
                    srcLinkInfo.column = depth
                if srcLinkInfo.getLinkNodeCnt() > 0:
                    continue
                depth = srcLinkInfo.column

            curDepth = depth
            if maxColNodes > 0:
                while curDepth < len(nodeGraph) and len(nodeGraph[curDepth]) >= maxColNodes:
                    curDepth += 1
            while len(nodeGraph) <= curDepth:
                nodeGraph.append([])
            nodeGraph[curDepth].append(node)
            srcs = {k.from_node for k in nodeTree.links if k.to_node == node}
            processNodes(
                srcNodeMap,
                nodeGraph,
                nodeTree,
                node,
                srcs,
                curDepth + 1,
                arrangeType,
                maxColNodes,
            )


def getNodeWidth(node):
    if node is None:
        return 0
    w = node.dimensions[0]
    return w if w > 0 else max(getattr(node, "width", 140.0), 140.0)


def getNodeHeight(node):
    if node is None:
        return 0
    h = node.dimensions[1]
    if h > 0:
        return h
    num_in = len([s for s in getattr(node, "inputs", []) if not getattr(s, "hide", False)])
    num_out = len([s for s in getattr(node, "outputs", []) if not getattr(s, "hide", False)])
    socks = max(num_in, num_out, 1)
    return max(getattr(node, "height", 100.0), 40.0 + socks * 24.0)


def displayNodes(nodeGraph, vAlign, xOffset, yOffset):
    origin = [0, 0]
    currLoc = origin[:]
    groupNodes = set()
    for origCol in nodeGraph:
        col = []  # Remove all None nodes to make logic easier
        for node in origCol:
            if node is not None:
                col.append(node)
        if len(col) == 0:
            continue
        if vAlign in {"MIDDLE", "BOTTOM"}:
            colHeight = sum(
                [getNodeHeight(n) for n in col]
            ) + yOffset * (len(col) - 1)
            currLoc[1] = (colHeight / 2) if vAlign == "MIDDLE" else colHeight
        maxWidth = max([getNodeWidth(n) for n in col])
        for i, node in enumerate(col):
            nodeW = getNodeWidth(node)
            loc = [currLoc[0] - (maxWidth + nodeW) / 2, currLoc[1]]
            if i > 0:
                prevNode = col[i - 1]
                loc[1] = prevNode.location[1] - getNodeHeight(prevNode) - yOffset
            node.location = loc
            if node.type == "GROUP":
                groupNodes.add(node)
        currLoc[0] -= maxWidth + xOffset
        currLoc[1] = 0
    return groupNodes


def getOverride():
    win = bpy.context.window
    screen = win.screen
    area = [a for a in screen.areas if a.type == "NODE_EDITOR"][0]
    region = [region for region in area.regions if region.type == "WINDOW"]
    return {"window": win, "screen": screen, "area": area, "region": region[0]}


def createSrcNodeMap(nodeTree):
    srcNodeMap = {}
    links = nodeTree.links
    for k in links:
        srcLinkInfo = srcNodeMap.get(k.from_node)
        if srcLinkInfo is None:
            srcLinkInfo = SrcLinkInfo()
            srcNodeMap[k.from_node] = srcLinkInfo
        srcLinkInfo.addLinkCnt(k.to_node)
    return srcNodeMap


def is_asset_node(node):
    """
    Check if a node or its node tree represents an asset node group
    (e.g., built-in essential assets, dynamics assets, or library assets).
    Internal trees of asset nodes should not be rearranged by lineupnodes.
    """
    if not node:
        return False

    child_tree = getattr(node, "node_tree", None)
    if child_tree is not None:
        # 1. Check standard Blender AssetMetaData
        if getattr(child_tree, "asset_data", None) is not None:
            return True

        # 2. Check custom property / ID flags
        if child_tree.get("is_asset", False) or child_tree.get("is_asset_node", False):
            return True

        # 3. Check if imported from external asset library
        if getattr(child_tree, "library", None) is not None:
            return True

        # 4. Check name against known built-in asset catalog
        tree_name = child_tree.name
        node_name = node.name
        try:
            from xnodify.asset_loader import KNOWN_ASSETS
            if tree_name in KNOWN_ASSETS or node_name in KNOWN_ASSETS:
                return True
        except Exception:
            try:
                from asset_loader import KNOWN_ASSETS
                if tree_name in KNOWN_ASSETS or node_name in KNOWN_ASSETS:
                    return True
            except Exception:
                try:
                    from refactor.asset_loader import KNOWN_ASSETS
                    if tree_name in KNOWN_ASSETS or node_name in KNOWN_ASSETS:
                        return True
                except Exception:
                    pass

    # Check node level properties
    if node.get("is_asset", False) or node.get("is_asset_node", False):
        return True

    return False


def displayTree(
    nodeTree, vAlign, xOffset, yOffset, includeGroup, arrangeType, maxColNodes, processedTrees=None
):
    if not nodeTree or not hasattr(nodeTree, "nodes") or len(nodeTree.nodes) == 0:
        return

    if processedTrees is None:
        processedTrees = set()

    if nodeTree in processedTrees:
        return
    processedTrees.add(nodeTree)

    srcNodeMap = createSrcNodeMap(nodeTree)
    nodeGraph = []
    nodes = nodeTree.nodes
    srcNodes = {n for n in nodes if (n in {k.from_node for k in nodeTree.links})}
    pureDestNodes = [n for n in nodes if n not in srcNodes]
    processNodes(
        srcNodeMap,
        nodeGraph,
        nodeTree,
        None,
        pureDestNodes,
        0,
        arrangeType,
        maxColNodes,
    )
    placedNodes = {n for col in nodeGraph for n in col if n is not None}
    unplacedNodes = [n for n in nodes if n not in placedNodes]
    if unplacedNodes:
        for node in unplacedNodes:
            colIdx = max(len(nodeGraph) - 1, 0)
            while maxColNodes > 0 and len(nodeGraph) > colIdx and len(nodeGraph[colIdx]) >= maxColNodes:
                colIdx += 1
            while len(nodeGraph) <= colIdx:
                nodeGraph.append([])
            nodeGraph[colIdx].append(node)
    groupNodes = displayNodes(nodeGraph, vAlign, xOffset, yOffset)

    if includeGroup:
        for node in groupNodes:
            childNodeTree = getattr(node, "node_tree", None)
            if not childNodeTree:
                continue

            # Exclude asset node groups from internal rearrangement
            if is_asset_node(node):
                continue

            if childNodeTree not in processedTrees:
                displayTree(
                    childNodeTree,
                    vAlign,
                    xOffset,
                    yOffset,
                    includeGroup=True,
                    arrangeType=arrangeType,
                    maxColNodes=maxColNodes,
                    processedTrees=processedTrees,
                )


def main(context, vAlign, xOffset, yOffset, includeGroup, arrangeType, maxColNodes):
    nodeTree = getActiveNodeTree(context)
    displayTree(
        nodeTree, vAlign, xOffset, yOffset, includeGroup, arrangeType, maxColNodes
    )


class LineupNodesParams(PropertyGroup):
    vAlign: EnumProperty(
        name="Vertical Alignment",
        description="Alignment nodes with tops at same level",
        items=(
            ("TOP", "Top", "Align top level of nodes"),
            ("MIDDLE", "Middle", "Align middle of nodes"),
            ("BOTTOM", "Bottom", "Align bottom   level of nodes"),
        ),
        default="MIDDLE",
    )
    arrangeType: EnumProperty(
        name="Arrange By",
        description="Arrange by nature of links",
        items=(
            ("FIRST", "First", "Put at first link column"),
            ("LAST", "Last", "Put at last link column"),
            ("MAX", "Max", "Put where links are maximum"),
        ),
        default="LAST",
    )
    xOffset: IntProperty(
        name="Width Separation",
        default=50,
        description="Separation between node columns",
    )

    yOffset: IntProperty(
        name="Height Separation", default=50, description="Separation between node rows"
    )

    includeGroup: BoolProperty(
        name="Include Group", default=True, description="Lineup group node tree"
    )

    maxColNodes: IntProperty(
        name="Max Column Nodes",
        default=10,
        description="Maximum count of nodes within column",
    )


class LineupNodesPanel(Panel):
    bl_label = "Line Up Nodes"
    bl_idname = "OBJECT_PT_lineupnodes"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "Edit"

    @staticmethod
    def drawPanel(col):
        params = bpy.context.window_manager.lineupNodeParams
        col.prop(params, "vAlign")
        col.prop(params, "arrangeType")
        col.prop(params, "xOffset")
        col.prop(params, "yOffset")
        col.prop(params, "maxColNodes")
        col.prop(params, "includeGroup")

    def draw(self, context):
        col = self.layout.column()
        LineupNodesPanel.drawPanel(col)
        col.operator("object.khema_lineupnodes")


class LineupNodesOp(Operator):
    bl_idname = "object.khema_lineupnodes"
    bl_label = "Line Up Nodes"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        params = bpy.context.window_manager.lineupNodeParams
        main(
            context,
            params.vAlign,
            params.xOffset,
            params.yOffset,
            params.includeGroup,
            params.arrangeType,
            params.maxColNodes,
        )
        return {"FINISHED"}


def register():
    bpy.utils.register_class(LineupNodesPanel)
    bpy.utils.register_class(LineupNodesOp)

    bpy.utils.register_class(LineupNodesParams)
    bpy.types.WindowManager.lineupNodeParams = bpy.props.PointerProperty(
        type=LineupNodesParams
    )


def unregister():
    del bpy.types.WindowManager.lineupNodeParams
    bpy.utils.unregister_class(LineupNodesParams)

    bpy.utils.unregister_class(LineupNodesOp)
    bpy.utils.unregister_class(LineupNodesPanel)
