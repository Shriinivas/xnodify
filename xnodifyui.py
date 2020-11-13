#
#
# UI classes and registration, unregistration functions for XNodify
#
# Copyright (C) 2020  Shrinivas Kulkarni
#
# License: GPL (https://github.com/Shriinivas/xnodify/blob/master/LICENSE)
#

import bpy, traceback
from bpy.props import StringProperty, FloatProperty, EnumProperty, BoolProperty
from bpy.types import PropertyGroup, Operator, Panel

from .lookups import nodeGroups, getCombinedMap, mathPrefix, vmathPrefix
from . main import procStringExpression, procScript, procFile, NodeLayout

# For debugging
from . import main
from . import lookups
import importlib
importlib.reload(main)
importlib.reload(lookups)

class XNodifyParams(PropertyGroup):

    def getTextEditorItems(dummy1, dummy2):
        return [(t.name, t.name, '') for t in bpy.data.texts]

    def getNodeGroups(dummy1, dummy2):
        return [(t[0], t[1], t[2]) for t in nodeGroups]

    def insertNodeDetails(self, context):
        if(self.singleMulti == 'MULTI'):
            if(self.internalExternal == 'INTERNAL'):
                script = bpy.data.texts[self.scriptName]
                lineIdx = script.current_line_index
                line = script.current_line.body
                charIdx = script.current_character
                script.current_line.body = \
                    line[:charIdx] + self.nodeName + line[charIdx:]
                script.cursor_set(lineIdx, \
                    character = charIdx + len(self.nodeName))
        else:
            self.expression += self.nodeName

    def getNodes(self, dummy2):
        group = self.nodeGroup
        items = []
        cMap = getCombinedMap()
        keys = [key for key in cMap.keys() if cMap[key][0] == group]
        for key in keys:
            if(group == '100'): fnName = key[len(mathPrefix):]
            elif(group == '200'): fnName = key[len(vmathPrefix):]
            else: fnName = key
            value = cMap[key]
            ips = value[3]
            ops = value[4]
            name = '%s - %s(%d, %d)' % (value[2], fnName, ips, ops)
            description = ('Symbol Name: %s (%d input' + \
                ('s' if ips > 1 else '') +' and %d output' + \
                    ('s' if ops > 1 else '') + ')') % (fnName, ips, ops)

            tKey = fnName + '(' + ''.join([',' for i in range(ips)]) + ')'
            items.append((tKey, name, description))
        return items

    singleMulti : EnumProperty(name='Single or Multiline', \
        items = ( ('SINGLE', 'Single Line', 'Nodes from single expression'), \
                  ('MULTI', 'Multiline', 'Nodes from script')),
        description='Create nodes from single expression or script', \
            default = 'SINGLE')

    internalExternal : EnumProperty(name='Internal or External', \
        items = ( ('INTERNAL', 'Internal', 'Internal Text Editor Script'), \
                  ('EXTERNAL', 'External', 'External .edf file')),
        description='Create nodes from single expression or script', \
            default = 'INTERNAL')

    scriptName : EnumProperty(name='Script', \
        items = getTextEditorItems, description='Select script')

    filePath : StringProperty(name = 'File Path', subtype='FILE_PATH')

    expression : StringProperty(name='Expression', default = '', \
        description='Expression to generate nodes')

    layoutExpanded : BoolProperty(name='Layout Options', default = False, \
        description='Options related to node layout')

    lookupExpanded : BoolProperty(name='Node Lookup', default = False, \
        description='Lookup of nodes and symbols')

    xScale : FloatProperty(name='X Scale', default = 1, \
        description='X scale for node layout')

    yScale : FloatProperty(name='Y Scale', default = 1, \
        description='Y scale for node layout')

    xLocation : FloatProperty(name='X Location', default = 0, \
        description='X location for node layout')

    yLocation : FloatProperty(name='Y Location', default = 0, \
        description='Y location for node layout')

    alignment : EnumProperty(name='Alignment', \
        items = (('TOP', 'Top', 'Top-alignment'), \
            ('CENTER', 'Center', 'Center-alignment'), \
            ('BOTTOM', 'Bottom', 'Bottom-alignment'), \
        ),
        default = 'TOP', \
        description='Vertical aligment of the node layout')

    addFrame : EnumProperty(name='Add Frame', \
        items = (('NEVER', 'Never', 'No frame created'), \
            ('MULTILINE', 'Multiline Only', \
                'Frame created only for multiline expressions'), \
            ('ALWAYS', 'Single Line & Multiline', 'Frame created for ' + \
                'multiline as well as sing line expressions'), \
        ),
        default = 'MULTILINE', \
        description='Option to add frame to newly created nodes')

    minimized : BoolProperty(name='Show Minimized', default = False, \
        description='Display nodes in minimized form')

    nodeGroup : EnumProperty(name='Node Category', \
        items = getNodeGroups, description='Select node category')

    nodeName : EnumProperty(name='Node', \
        items = getNodes, description='Select node to be inserted', \
        update = insertNodeDetails)


class XNodifyBaseOp(Operator):
    def modal (self, context, event):
        MAX_TRIES = 100
        if(event.type == 'TIMER'):
            done = NodeLayout.arrangeNodeLines(self.displayParams, \
                testDimensions = self.tryCnt < MAX_TRIES)
            if(done):
                context.window_manager.event_timer_remove(self._timer)
                return {"FINISHED"}
            self.tryCnt += 1
        return {"PASS_THROUGH"}

    def _execute(self, context):
        raise NotImplementedError('Call to abstract method')

    def execute(self, context):
        self.tryCnt = 0
        try:
            self.displayParams = self._execute(context)

            for lineNo in self.displayParams.warnings.keys():
                warningLines = '; '.join(self.displayParams.warnings[lineNo])
                self.report({'WARNING'}, 'LINE: ' + str(lineNo) + \
                    ' ' + warningLines)

            # Actual arranging is deferred
            # as dimensions are not available right now
            wm = context.window_manager
            self._timer = wm.event_timer_add(time_step = 0.01, \
                window = context.window)
            wm.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        except Exception as e:
            traceback.print_exc()
            self.report({'ERROR'}, str(e))
        return {'FINISHED'}

class XNodifyOp(XNodifyBaseOp):
    bl_idname = 'object.xnodify'
    bl_label = 'Generate Nodes'
    bl_options = {'REGISTER', 'UNDO'}

    def _execute(self, context):
        params = context.window_manager.XNodifyParams
        if(params.singleMulti == 'SINGLE'):
            expression = context.window_manager.XNodifyParams.expression
            return main.procStringExpression(expression,\
                (params.xLocation, params.yLocation), \
                    (params.xScale, params.yScale), params.alignment, \
                        params.addFrame == 'ALWAYS', params.minimized)
        elif(params.internalExternal == 'INTERNAL'):
            return main.procScript(params.scriptName,\
                (params.xLocation, params.yLocation), \
                    (params.xScale, params.yScale), params.alignment, \
                        params.addFrame != 'NEVER', params.minimized)
        else:
            return bpy.path.abspath(params.filePath)
            self.displayParams = main.procFile(filePath,\
                (params.xLocation, params.yLocation), \
                    (params.xScale, params.yScale), params.alignment, \
                        params.addFrame != 'NEVER', params.minimized)

class XNodifyPanel(Panel):
    bl_label = 'XNodify'
    bl_idname = 'NODE_PT_xnodify'
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = 'Edit'

    def draw(self, context):
        params = context.window_manager.XNodifyParams
        layout = self.layout

        col = layout.column()
        row = col.row()
        row.prop(params, 'singleMulti', expand=True)

        if(params.singleMulti == 'SINGLE'):
            row = col.row()
            row.prop(params, 'expression')
        else:
            row = col.row()
            row.prop(params, 'internalExternal', expand=True)
            row = col.row()
            if(params.internalExternal == 'INTERNAL'):
                row.prop(params, 'scriptName')
            else:
                col.prop(params, 'filePath', text = 'File Path')

        row = col.row()
        row.prop(params, 'layoutExpanded',
            icon='TRIA_DOWN' if params.layoutExpanded else 'TRIA_RIGHT',
            icon_only=True, emboss=False
        )
        row.label(text='Node Layout Options')
        if params.layoutExpanded:
            row = col.row()
            row.label(text = 'Scale')
            row.prop(params, 'xScale', text = '')
            row.prop(params, 'yScale', text = '')
            row = col.row()
            row.label(text = 'Location')
            row.prop(params, 'xLocation', text = '')
            row.prop(params, 'yLocation', text = '')
            col.prop(params, 'alignment', text = 'Alignment')
            col.prop(params, 'addFrame', text = 'Add Frame')
            col.prop(params, 'minimized', text = 'Show Minimized')

        row = col.row()
        row.prop(params, 'lookupExpanded',
            icon='TRIA_DOWN' if params.lookupExpanded else 'TRIA_RIGHT',
            icon_only=True, emboss=False
        )
        row.label(text='Node Look-up')
        if params.lookupExpanded:
            row = col.row()
            row.prop(params, 'nodeGroup', text = 'Node Group')
            row = col.row()
            row.prop(params, 'nodeName', text = 'Node')

        col.operator('object.xnodify')

def register():
    bpy.utils.register_class(XNodifyPanel)
    bpy.utils.register_class(XNodifyOp)

    bpy.utils.register_class(XNodifyParams)
    bpy.types.WindowManager.XNodifyParams = \
        bpy.props.PointerProperty(type = XNodifyParams)

def unregister():
    del bpy.types.WindowManager.XNodifyParams
    bpy.utils.unregister_class(XNodifyParams)

    bpy.utils.unregister_class(XNodifyOp)
    bpy.utils.unregister_class(XNodifyPanel)
