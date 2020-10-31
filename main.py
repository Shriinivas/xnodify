#
# Main module of XNodify.
# Includes classes that create and arrange nodes from parsed tokens.
#
# Copyright (C) 2020  Shrinivas Kulkarni
#
# License: GPL (https://github.com/Shriinivas/xnodify/blob/master/LICENSE)
#

import bpy
from mathutils import Vector

from .lookups import getCombinedMap

# For debug
from . import parser, lookups, evaluator
import importlib
importlib.reload(parser)
importlib.reload(lookups)
importlib.reload(evaluator)

from . evaluator import NumberEvaluator, VariableEvaluator, EqualsEvaluator
from . evaluator import PlusEvaluator, MultiplyEvaluator, DivisionEvaluator
from . evaluator import PowerEvaluator, ParenthesisEvaluator, EvaluatorBase

# Message bus to exchange data between objects
class EvalParamsBus:
    @staticmethod
    def getNodeSocket(data, node, out = True, defaultIdx = 0):
        if(data == None or node == None):
            return None
        if(out):
            sockets = [o for o in node.outputs \
                if o.enabled == True and o.hide == False]
        else:
            sockets = [i for i in node.inputs \
                if i.enabled == True and i.hide == False]

        if(data.sockIdx == None and len(sockets) > 0):
            return sockets[defaultIdx] if(defaultIdx != None and \
                len(sockets) > defaultIdx) else None

        socket = None
        try:
            socket = sockets[int(data.sockIdx)]
        except Exception as e:
            print(e)
            try:
                socket = sockets[data.sockIdx]
            except Exception as e2:
                print(e2)
                if(len(node.outputs) > 0):
                    socket = sockets[0]
        return socket

    def __init__(self, data, operand0, operands1):
        self.data = data
        self.operand0 = operand0
        self.operands1 = operands1
        self.lhsNode = None
        self.rhsNodes = None

    def setLHSNode(self, lhsNode):
        self.lhsNode = lhsNode

    def setRHSNodes(self, rhsNodes):
        self.rhsNodes = rhsNodes

    def getDefLHSOutput(self):
        if(self.lhsNode != None and self.operand0 != None):
           return EvalParamsBus.getNodeSocket(self.operand0, self.lhsNode, True)
        return None

    def getRHSOutputs(self):
        if(self.operands1 == None):
            return None
        outputs = []
        for i, s in enumerate(self.operands1):
            socket = EvalParamsBus.getNodeSocket(s, self.rhsNodes[i])
            outputs.append(socket)
        return outputs

    def getDefRHSOutput(self):
        outputs = self.getRHSOutputs()
        return None if outputs == None else outputs[0]

class SymbolData(object):
    def __init__(self, id, meta, value):
        self.meta = meta
        self.value = value
        self.operand0 = self.operand1 = None
        # self.operand2... Ternary not supported for now
        self.isFn = False # TODO: Separate class? (part of meta actually)
        self.isGroup = False # TODO: Separate class? (part of meta actually)
        self.sockIdx = None # Index in [] operator TODO: separate class?
        self.isLHS = False # TODO: Separate class?
        self.evaluator = EvaluatorBase.getEvaluator(id)

    def getLinearList(self, items):
        items.append(self)
        if isinstance(self.operand0,  SymbolData):
            self.operand0.getLinearList(items)

        if isinstance(self.operand1,  SymbolData):
            operands1 = [self.operand1]
        elif isinstance(self.operand1,  list):
            operands1 = self.operand1
        else:
            operands1 = []

        for operand in operands1:
            if(operand != None):
                operand.getLinearList(items)

        return items

    def getMetaData(self):
        return self.meta

    # Assuming operand0 i.e. LHS of the operator will always be a single element
    # operand1 can be a list (function arguments for example);
    # So in case of prefix operators with a list as operand0,
    # this will need to be changed
    def evalSymbol(self, nodeTree, varTable, afterProcNode, colNo = 0):
        if(self.evaluator == None):
            return None

        operand0 = self.operand0

        if isinstance(self.operand1,  SymbolData):
            operands1 = [self.operand1]
        elif isinstance(self.operand1,  list):
            operands1 = self.operand1
        else:
            operands1 = None

        paramBus = EvalParamsBus(self, operand0, operands1)

        nodeTree = self.evaluator.beforeOperand0(nodeTree, paramBus)

        if isinstance(operand0,  SymbolData):
            # TODO: Hack...a better way to achieve this
            if(self.getMetaData().id in {'='}):
                nextColNo = colNo
            else:
                nextColNo = colNo + 1
            lhsNode = operand0.evalSymbol(nodeTree, varTable, \
                afterProcNode, nextColNo)
        else:
            lhsNode = None

        paramBus.setLHSNode(lhsNode)

        nodeTree = self.evaluator.beforeOperand1(nodeTree, paramBus)

        nextColNo = colNo + 1
        if(operands1 == None):
            rhsNodes = None
        else:
            rhsNodes = []
            for s in operands1:
                if(s != None):
                    rhsNode = s.evalSymbol(nodeTree, varTable, \
                        afterProcNode, nextColNo)
                    rhsNodes.append(rhsNode)
                else:
                    rhsNodes.append(None)

        paramBus.setRHSNodes(rhsNodes)

        node = self.evaluator.evaluate(nodeTree, paramBus, varTable)

        # afterProcNode: callback after processing each token
        afterProcNode(colNo, node, paramBus, varTable)

        return node

class NodeLayout:
    noodleWidth = 80
    frameMargins = ((20, 40), (20, 20))

    # Normalize the nodegraph to remove gaps in columns and rows
    def __init__(self, tNodeGraph):
        self.colHeights = []
        self.colWidths = []
        self.nodeGraph = []
        for col in sorted(tNodeGraph.keys()):
            self.nodeGraph.append([])
            self.colHeights.append(0)
            self.colWidths.append(0)
            for row in range(len(tNodeGraph[col])):
                node = tNodeGraph[col][row]
                self.nodeGraph[-1].append(node)
                dimensions = EvaluatorBase.getNodeDimensions(node)
                self.colHeights[-1] += dimensions[1]
                if(self.colWidths[-1] < dimensions[0]):
                    self.colWidths[-1] = dimensions[0]

        self.nodeCnt = len(self.colHeights)
        self.totalHeight = max(self.colHeights) if(self.nodeCnt > 0) else 0
        self.totalWidth = (sum(self.colWidths) + \
            (self.nodeCnt - 1) * NodeLayout.noodleWidth) \
                if(self.nodeCnt > 0) else 0

# One per line
class Controller:
    def __init__(self, varNodeGraphs, currNodes):
        self.nodeTreeTable = {}
        self.varNodeGraphs = varNodeGraphs
        self.currNodes = currNodes if currNodes != None else set()

    def getGlobalNodes(self):
        allNodes = set()
        for nodeTree in self.nodeTreeTable.keys():
            nodeGraph = self.nodeTreeTable[nodeTree]
            for col in nodeGraph.keys():
                allNodes = allNodes.union(nodeGraph[col])
        allNodes = allNodes.union(self.currNodes)
        return allNodes

    def removeAllNodes(self, newNodes = None):
        for node in self.getGlobalNodes():
            node.id_data.nodes.remove(node)
        # TODO : better way to delete all nodes on syntax error
        if(newNodes != None):
            for node in newNodes:
                try:
                    node.id_data.nodes.remove(node)
                except:
                    pass

    # Callback method, creates and updates nodeTreeTable used by arrange.
    # nodeTreeTable will have mulitple nodeGraphs only in case of group nodes.
    def afterProcNode(self, colNo, node, params, varTable):
        if(node != None and node not in self.getGlobalNodes()):
            nodeTree = node.id_data
            nodeGraph = self.nodeTreeTable.get(nodeTree)
            if(nodeGraph == None):
                self.nodeTreeTable[nodeTree] = {}
                nodeGraph = self.nodeTreeTable[nodeTree]

            # add varTable node (and its associated nodes) at its first usage
            # TODO: Review
            if(params.data.value in self.varNodeGraphs.keys()):
                varTreeTable = self.varNodeGraphs[params.data.value]
                for key in varTreeTable.keys():
                    nodeInfo = varTable[params.data.value]
                    if(key != nodeInfo[0].id_data):
                        continue
                    nodeLayout = NodeLayout(varTreeTable[key])
                    colHeights, colWidths, varNodeGraph = \
                        nodeLayout.colHeights, nodeLayout.colWidths, \
                            nodeLayout.nodeGraph

                    for col in range(len(varNodeGraph)):
                        for row in reversed(range(len(varNodeGraph[col]))):
                            varNode = varNodeGraph[col][row]
                            if(varNode.bl_idname == 'ShaderNodeGroup'):
                                self.nodeTreeTable[varNode.node_tree] = \
                                    varTreeTable[varNode.node_tree]
                            newCol = colNo + col
                            nodeColumn = nodeGraph.get(newCol)
                            if(nodeColumn == None):
                                nodeGraph[newCol] = []
                                nodeColumn = nodeGraph[newCol]
                            nodeColumn.insert(0, varNode)
                self.varNodeGraphs.pop(params.data.value)
            else:
                nodeColumn = nodeGraph.get(colNo)
                if(nodeColumn == None):
                    nodeGraph[colNo] = []
                    nodeColumn = nodeGraph[colNo]
                nodeColumn.append(node)

    # At this point all nodes are already created and links established
    @staticmethod
    def arrangeNodes(nodeTreeTable, nodeTree, \
        location, scale, alignment, nodeLayout = None):

        height = 0
        width = 0

        if(nodeLayout == None):
            nodeLayout = NodeLayout(nodeTreeTable[nodeTree])

        colHeights, colWidths, totalHeight, totalWidth, nodeGraph = \
            nodeLayout.colHeights, nodeLayout.colWidths, \
                nodeLayout.totalHeight, nodeLayout.totalWidth, \
                    nodeLayout.nodeGraph

        for col in range(len(nodeGraph)):
            yOffset = 0
            if(alignment == 'CENTER'):
                yOffset = (totalHeight - colHeights[col]) / 2
            elif(alignment == 'BOTTOM'):
                yOffset = (totalHeight - colHeights[col])

            prevHeight = 0
            for row in range(len(nodeGraph[col])):
                node = nodeGraph[col][row]
                dimensions = EvaluatorBase.getNodeDimensions(node)
                x = totalWidth / 2 -  sum(colWidths[:col + 1]) - \
                    col * NodeLayout.noodleWidth + \
                        (colWidths[col] - dimensions[0]) / 2
                y =  prevHeight + yOffset
                prevHeight += dimensions[1]

                nodeLoc = Vector((location[0] + scale[0] * x, \
                    location[1] + -scale[1] * y))
                node.location = nodeLoc

                if(node.bl_idname == 'ShaderNodeGroup'):
                    refLocation =  -node.id_data.view_center + nodeLoc
                    gTotalWidth, gTotalHeight = \
                        Controller.arrangeNodes(nodeTreeTable, node.node_tree, \
                            refLocation, scale, alignment)
                    nOut = node.node_tree.nodes['Group Output']
                    nOut.location = refLocation
                    nOut.location[0] += \
                        NodeLayout.noodleWidth + gTotalWidth / 2
                    nIn = node.node_tree.nodes['Group Input']
                    nIn.location = refLocation
                    nIn.location[0] -= NodeLayout.noodleWidth + \
                        gTotalWidth / 2 + \
                            EvaluatorBase.getNodeDimensions(nIn)[0]

        return totalWidth, totalHeight

    def createNodes(self, nodeTree, varTable, expression, depth = 0):
        dataTree = parser.parse(expression, SymbolData)

        if(dataTree == None):
            return None, None, None

        datas = dataTree.getLinearList([])
        equalsOps = [t for t in datas if t.getMetaData().id == '=']

        if(len(equalsOps) > 1):
            raise SyntaxError('Only one assignment allowed in a line.')
        elif(len(equalsOps) == 1):
            op0 = equalsOps[0].operand0
            if(op0.getMetaData().id != 'NAME'):
                raise SyntaxError('LHS must be a variable or the output node')
            if(op0.value == 'output'):
                exprType = 'output'
            elif(op0.value in getCombinedMap().keys()):
                raise SyntaxError('LHS cannot refer to a node ' + \
                    'other than output')
            else:
                exprType = op0.value
        elif(len(equalsOps) == 0):
            exprType = None

        dataTree.evalSymbol(nodeTree, varTable, self.afterProcNode, depth)
        return exprType, self.nodeTreeTable, self.getGlobalNodes()

# Context for all the lines
class XNodifyContext:

    @staticmethod
    def hardReplace(expression, hardReplaceTable):
        for key in hardReplaceTable:
            expression = expression.replace('`'+key+'`', hardReplaceTable[key])
        return expression

    def __init__(self):
        pass

    def processExpressions(self, lineFeeder, nodeTree, \
        location, scale, alignment, addFrame, frameTitle = None):
        if(nodeTree == None):
            nodeTree = XNodifyContext.getActiveMatTree()
        actLineCnt = 1
        varNodes = set()
        try:
            expression = next(lineFeeder)
            varTable = {}
            varNodeGraphs = {}
            hardReplaceTable = {}
            allNodes = set()
            lineNodeTables = []
            lineCnt = 0
            while(expression != None):
                expression = expression.strip()
                expression = XNodifyContext.hardReplace(expression, \
                    hardReplaceTable)
                controller = Controller(varNodeGraphs, allNodes)
                exprType, nodeTreeTable, newNodes = \
                    controller.createNodes(nodeTree, varTable, expression)

                if(exprType != None):
                    lhs, rhs = expression.split('=')
                    hardReplaceTable[lhs.strip()] = rhs.strip()

                if(nodeTreeTable != None):
                    if(exprType != None and exprType != 'output'):
                        varNodes = varNodes.union(newNodes)
                        varNodeGraphs[exprType] = nodeTreeTable
                        nType = 'var'
                    else:
                        allNodes = allNodes.union(newNodes)
                        nType = 'line'
                    lineNodeTables.append((nType, nodeTreeTable, actLineCnt))
                    lineCnt += 1
                expression = next(lineFeeder)
                actLineCnt += 1

            height = 0
            varTreeTables = varNodeGraphs.values()
            frameHeight = (70 if addFrame else 30) * scale[1]

            for i in range(lineCnt):
                nType, nodeTreeTable, actLineCnt = lineNodeTables[i]
                if(nType == 'line' or nodeTreeTable in varTreeTables):
                    nodeLayout = NodeLayout(nodeTreeTable[nodeTree])
                    newLoc = Vector(location) + Vector((0, -height))
                    Controller.arrangeNodes(nodeTreeTable, nodeTree, \
                        newLoc, scale, alignment, nodeLayout)
                    if(addFrame):
                        frame = nodeTree.nodes.new(type='NodeFrame')
                        frame.label = frameTitle if frameTitle != None \
                            else 'Line ' + str((actLineCnt))
                        for col in range(len(nodeLayout.nodeGraph)):
                            for row in range(len(nodeLayout.nodeGraph[col])):
                                nodeLayout.nodeGraph[col][row].parent = frame
                    height += nodeLayout.totalHeight + frameHeight

        except Exception as e:
            controller.removeAllNodes(varNodes)
            raise SyntaxError('Line: ' + str(actLineCnt) + ': ' + str(e))

def getActiveMatTree():
    obj = bpy.context.active_object
    if(obj == None):
        return None
    mat = obj.active_material
    if(mat == None):
        return None

    mat.use_nodes = True
    return mat.node_tree

def procScript(scriptName, location, scale, alignment, addFrame):
    def scriptLineFeeder(scriptName):
        for line in bpy.data.texts[scriptName].lines:
            yield line.body
        yield None

    XNodifyContext().processExpressions(scriptLineFeeder(scriptName), \
        getActiveMatTree(), location, scale, alignment, addFrame)

def procFile(filePath, location, scale, alignment, addFrame):
    def fileLineFeeder(filePath):
        with open(filePath) as f:
            line = f.readline()
            while(line):
                yield line
                line = f.readline()
        yield None

    XNodifyContext().processExpressions(fileLineFeeder(filePath), \
        getActiveMatTree(), location, scale, alignment, addFrame)

def procSingleExpression(expression, location, scale, alignment, addFrame):
    def feeder():
        for e in [expression, None]:
            yield e
    XNodifyContext().processExpressions(feeder(), getActiveMatTree(), \
        location, scale, alignment, addFrame, 'Expression')

