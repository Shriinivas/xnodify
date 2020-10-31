#
# Evaluator classes for XNodify.
# Each class generates the nodes corresponding to the specific operator
#
# Copyright (C) 2020  Shrinivas Kulkarni
#
# License: GPL (https://github.com/Shriinivas/xnodify/blob/master/LICENSE)
#

import bpy
from mathutils import Vector

from .lookups import fnMap, mathFnMap, vmathFnMap, mathPrefix, vmathPrefix
from .lookups import reverseLookup

class EvaluatorBase:

###################### Helpers ###############################
    @staticmethod
    def getEvaluator(id):
        if(id == '='):
            return EqualsEvaluator()
        elif(id == '+'):
            return PlusEvaluator()
        elif(id == '-'):
            return MinusEvaluator()
        elif(id == '*'):
            return MultiplyEvaluator()
        elif(id == '**'):
            return PowerEvaluator()
        elif(id == '/'):
            return DivisionEvaluator()
        elif(id == '('):
            return ParenthesisEvaluator()
        # ~ elif(id == '['): # Taken care in parser
            # ~ return BracketSymbol()
        elif(id == '{'):
            return BraceEvaluator()
        elif(id == 'NAME'):
            return VariableEvaluator()
        elif(id == 'NUMBER'):
            return NumberEvaluator()
        return None

    @staticmethod
    def getNodeDimensions(node):

        # TODO!!
        def getCntForType(socket):
            if(socket.type == 'VECTOR'): return 1
            else: return 1

        if(node.bl_idname in {'ShaderNodeMath', 'ShaderNodeVectorMath'}):
            lookupKey = node.bl_idname + '_' + node.operation
        else:
            lookupKey = node.bl_idname
        customName = reverseLookup(lookupKey)
        if(customName.startswith(mathPrefix)):
            fnInfo = mathFnMap.get(customName)
        elif(customName.startswith(vmathPrefix)):
            fnInfo = vmathFnMap.get(customName)
        else:
            fnInfo = fnMap.get(customName)
        dimensions = fnInfo[5]
        if(node.bl_idname == 'ShaderNodeGroup'):
            socketHeight = 22
            opCnts = sum([getCntForType(o) for o in node.outputs \
                if o.enabled == True and o.hide == False])
            ipCnt = sum([getCntForType(i) for i in node.inputs \
                if i.enabled == True and i.hide == False])
            dimensions = (dimensions[0], dimensions[1] + \
                (opCnts + ipCnt) * socketHeight)

        return Vector(dimensions)

    @staticmethod
    def getNode(nodeTree, customName, label = None, value = None):
        node = nodeTree.nodes.new(customName)
        if(value != None):
            node.outputs[0].default_value = float(value)
        if(label != None):
            node.label = label
        return node

    @staticmethod
    def getPrimitiveMathNode(nodeTree, operation, label, op0, op1):
        node = EvaluatorBase.getNode(nodeTree, 'ShaderNodeMath', label)
        node.operation = operation
        nodeTree.links.new(op0, node.inputs[0])
        nodeTree.links.new(op1, node.inputs[1])
        return node

    def __init__(self):
        pass

    def beforeOperand0(self, nodeTree, paramBus):
        return nodeTree

    def beforeOperand1(self, nodeTree, paramBus):
        return nodeTree

    def evaluate(self, nodeTree, paramBus, varTable):
        raise SyntaxError('Unsupported function!')

class NumberEvaluator(EvaluatorBase):
    def evaluate(self, nodeTree, paramBus, varTable):
        return EvaluatorBase.getNode(nodeTree, 'ShaderNodeValue', \
            value = paramBus.data.value)


class VariableEvaluator(EvaluatorBase):
    def evaluate(self, nodeTree, paramBus, varTable):
        data = paramBus.data

         # Functions are handled in evalParenthesis
        if(data.isFn or data.isGroup):
            return None

        varName = data.value

        # ~ if(fnMap.get(varName) != None): # Allow this now
            # ~ raise SyntaxError(varName, 'is a function, ' + \
                         # ~ 'it can\'t be a variable name')

        # Math functions are handled in evalParenthesis
        nodeInfo = fnMap.get(varName)
        if(nodeInfo != None):
            node = EvaluatorBase.getNode(nodeTree, \
                nodeInfo[1], nodeInfo[2])
        else:
            varTableInfo = varTable.get(varName)
            if(varTableInfo != None):
                node, sockIdx = varTableInfo
                if(nodeTree != node.id_data):
                    raise SyntaxError('Groups cannot contain ' + \
                        'variables defined earlier')

                if(sockIdx != None):
                    paramBus.data.sockIdx = sockIdx
            else:
                # LHS is handled in evalEquals
                if(data.isLHS):
                    return None
                node = EvaluatorBase.getNode(nodeTree, \
                    'ShaderNodeValue', data.value, 0)
                varTable[varName] = (node, 0)

        return node


class EqualsEvaluator(EvaluatorBase):
    def evaluate(self, nodeTree, paramBus, varTable):
        operand0 = paramBus.operand0
        operands1 = paramBus.operands1

        lhsNode = paramBus.lhsNode
        rhsNodes = paramBus.rhsNodes

        if(lhsNode == None):# and operand0.isLHS):
            varTable[operand0.value] = (rhsNodes[0], operands1[0].sockIdx)
            return None
        elif(len(lhsNode.inputs) == 0):
            raise SyntaxError('Left hand side should be ' + \
                'a node type with at least one input')

        ip = paramBus.getNodeSocket(operand0, lhsNode, out = False)

        # Get the first free input of lhs
        i = 0
        if(len(ip.links) != 0):
            ip = lhsNode.inputs[i]
            while(i < len(lhsNode.inputs) and len(ip.links) != 0):
                ip = lhsNode.inputs[i]
                i += 1

        if(i == len(lhsNode.inputs)):
            raise SyntaxError('Left hand side of "=" should be ' + \
                'a node type with at least one free input')

        op = paramBus.getNodeSocket(operands1[0], rhsNodes[0])
        if(op == None):
            raise SyntaxError('Right hand side of "=" should be ' + \
                'a node type with at least one output')

        nodeTree.links.new(ip, op)
        return None


class PlusEvaluator(EvaluatorBase):
    def evaluate(self, nodeTree, paramBus, varTable):
        return EvaluatorBase.getPrimitiveMathNode(nodeTree, \
            'ADD', 'Add', paramBus.getDefLHSOutput(), \
                paramBus.getDefRHSOutput())

class MinusEvaluator(EvaluatorBase):
    def evaluate(self, nodeTree, paramBus, varTable):
        return EvaluatorBase.getPrimitiveMathNode(nodeTree, \
            'SUBTRACT', 'Subtract', paramBus.getDefLHSOutput(), \
                paramBus.getDefRHSOutput())

class MultiplyEvaluator(EvaluatorBase):
    def evaluate(self, nodeTree, paramBus, varTable):
        return EvaluatorBase.getPrimitiveMathNode(nodeTree, \
            'MULTIPLY', 'Multiply', paramBus.getDefLHSOutput(), \
                paramBus.getDefRHSOutput())

class DivisionEvaluator(EvaluatorBase):
    def evaluate(self, nodeTree, paramBus, varTable):
        return EvaluatorBase.getPrimitiveMathNode(nodeTree, \
            'DIVIDE', 'Divide', paramBus.getDefLHSOutput(), \
                paramBus.getDefRHSOutput())

class PowerEvaluator(EvaluatorBase):
    def evaluate(self, nodeTree, paramBus, varTable):
        return EvaluatorBase.getPrimitiveMathNode(nodeTree, \
            'POWER', 'Power', paramBus.getDefLHSOutput(), \
                paramBus.getDefRHSOutput())

class ParenthesisEvaluator(EvaluatorBase):
    def evaluate(self, nodeTree, paramBus, varTable):
        node = customName = None
        fnName = paramBus.operand0.value
        fn = fnMap.get(fnName)
        if(fn != None):
            node = EvaluatorBase.getNode(nodeTree, fn[1], fn[2])
            customName = fnName
        else:
            fn = mathFnMap.get(mathPrefix + fnName)
            if(fn != None):
                node = EvaluatorBase.getNode(nodeTree, 'ShaderNodeMath', fn[2])
                node.operation = fn[1]
                customName = mathPrefix + fnName
            else:
                fn = vmathFnMap.get(vmathPrefix + fnName)
                if(fn != None):
                    node = EvaluatorBase.getNode(nodeTree, \
                        'ShaderNodeVectorMath', fn[2])
                    node.operation = fn[1]
                    customName = vmathPrefix + fnName
        if(node != None):
            outputs = paramBus.getRHSOutputs()
            inputs = [ip for ip in node.inputs if ip.enabled == True]
            for i in range(min(len(outputs), len(inputs))):
                if(inputs[i] != None and outputs[i] != None):
                    nodeTree.links.new(outputs[i], inputs[i])
            return node
        raise SyntaxError('Unknown Function: '+ paramBus.operand0.value)

class BraceEvaluator(EvaluatorBase):

    def beforeOperand1(self, nodeTree, paramBus):
        if(paramBus.operand0 == None):
            groupName = 'XNodifyNodeGroup'
        else:
            groupName = paramBus.operand0.value
        group = nodeTree.nodes.new('ShaderNodeGroup')
        group.name = groupName
        gNodeTree = bpy.data.node_groups.new(groupName, 'ShaderNodeTree')
        group.node_tree = gNodeTree
        gNodeTree.nodes.new('NodeGroupOutput')
        gNodeTree.nodes[-1].name = gNodeTree.nodes[-1].label = 'Group Output'
        gNodeTree.nodes.new('NodeGroupInput')
        gNodeTree.nodes[-1].name = gNodeTree.nodes[-1].label = 'Group Input'
        paramBus.groupNode = group # Temporarily created will be used below
        return gNodeTree

    def evaluate(self, nodeTree, paramBus, varTable):
        nodes = nodeTree.nodes
        links = nodeTree.links
        gOutput = nodes[0]
        gInput = nodes[1]

        for node in paramBus.rhsNodes:
            outputs = [o for o in node.outputs \
                if o.enabled == True and o.hide == False]
            for op in outputs:
                if(len(op.links) == 0):
                    gIp = gOutput.inputs.new(op.bl_idname, op.name)
                    links.new(gIp, op)
        for node in paramBus.rhsNodes:
            inputs = [i for i in node.inputs \
                if i.enabled == True and i.hide == False]
            for ip in inputs:
                if(len(ip.links) == 0):
                    gOp = gInput.outputs.new(ip.bl_idname, ip.name)
                    links.new(ip, gOp)

        return paramBus.groupNode # Created above in beforeOperand1 method
