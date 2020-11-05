#
# Generic Parser of XNodify add-on.
#
# Implements Pratt Parser
# (For a good explanation: http://effbot.org/zone/simple-top-down-parsing.html)
#
# Copyright (C) 2020  Shrinivas Kulkarni
#
# License: GPL (https://github.com/Shriinivas/xnodify/blob/master/LICENSE)
#

import tokenize
from io import StringIO

def validateNext(id = None):
    global _gNextData, _gtokenizer
    if id and _gNextData.getMetaData().id != id:
        raise SyntaxError('Expected %r' % id)
    _gNextData = next(_gtokenizer)

class SymbolBase(object):
    def __init__(self, id, precedence = 0):
        self.id = id
        self.precedence = precedence

    def procPrefix(self, sdata):
        raise SyntaxError('Syntax error (%r).' % self.id)

    def procInfix(self, sdata, left):
        raise SyntaxError('Unknown operator (%r).' % self.id)

class NameSymbol(SymbolBase):
    def procPrefix(self, sdata):
        return sdata

class NumberSymbol(SymbolBase):
    def procPrefix(self, sdata):
        return sdata

class InfixSymbol(SymbolBase):
    def procInfix(self, sdata, left):
        sdata.operand0 = left
        sdata.operand1 = parseExpression(self.precedence)
        return sdata

# ~ class PrefixSymbol(SymbolBase):
    # ~ def procPrefix(self, sdata):
        # ~ sdata.operand0 = parseExpression(self.precedence)
        # ~ return sdata

class PrefixInfixSymbol(SymbolBase):
    def __init__(self, id, iPriority, pPriority):
        super(PrefixInfixSymbol, self).__init__(id, iPriority)
        self.iPriority = iPriority
        self.pPriority = pPriority

    def procPrefix(self, sdata):
        sdata.operand0 = parseExpression(self.pPriority)

        # Ideally these should be separate classes, but...
        # making exceptions to the rule to avoid extra coding
        if(sdata.getMetaData().id == '+'):
            return sdata.operand0
        elif(sdata.getMetaData().id == '-'):
            if(sdata.operand0.getMetaData().id != 'NUMBER'):
                raise SyntaxError('- sign can be followed only by a number')
            sdata.operand0.value = str(-1 * float(sdata.operand0.value))
            return sdata.operand0
        return sdata

    def procInfix(self, sdata, left):
        sdata.operand0 = left
        sdata.operand1 = parseExpression(self.iPriority)
        return sdata

class PairedSymbol(SymbolBase):
    def __init__(self, id, precedence, startChar, endChar):
        super(PairedSymbol, self).__init__(id, precedence)
        self.startChar = startChar
        self.endChar = endChar

    def procPrefix(self, sdata):
        d = parseExpression()
        validateNext(self.endChar)
        return d

    def procInfix(self, sdata, left):
        sdata.operand0 = left
        sdata.operand1 = []
        if _gNextData.getMetaData().id != self.endChar:
            while 1:
                # For XNodify: Allow blanks before and after ,
                if(_gNextData.getMetaData().id == ','):
                    sdata.operand1.append(None)
                elif(_gNextData.getMetaData().id == self.endChar):
                    sdata.operand1.append(None)
                    break
                else:
                    sdata.operand1.append(parseExpression())
                    if _gNextData.getMetaData().id != ',':
                        break
                validateNext(',')
        validateNext(self.endChar)
        return sdata

class ParenthesisSymbol(PairedSymbol):
    def __init__(self, id, precedence = 0):
        super(ParenthesisSymbol, self).__init__(id, precedence, '(', ')')

    def procInfix(self, sdata, left):
        retVal = super(ParenthesisSymbol, self).procInfix(sdata, left)
        sdata.operand0.isFn = True
        return retVal

class BracketSymbol(PairedSymbol):
    def __init__(self, id, precedence = 0):
        super(BracketSymbol, self).__init__(id, precedence, '[', ']')

    def procInfix(self, sdata, left):
        retVal = super(BracketSymbol, self).procInfix(sdata, left)
        sdata.operand0.sockIdx = sdata.operand1[0].value #TODO: validation
        return sdata.operand0 # Just a small trick...

class BraceSymbol(PairedSymbol):
    def __init__(self, id, precedence = 0):
        super(BraceSymbol, self).__init__(id, precedence, '{', '}')

    def procInfix(self, sdata, left):
        retVal = super(BraceSymbol, self).procInfix(sdata, left)
        sdata.operand0.isGroup = True
        return retVal

class EqualsSymbol(InfixSymbol):
    def __init__(self, id, precedence = 0):
        super(EqualsSymbol, self).__init__(id, precedence)

    def procInfix(self, sdata, left):
        retVal = super(EqualsSymbol, self).procInfix(sdata, left)
        sdata.operand0.isLHS = True # More tricks.. careful!
        # ~ sdata = left
        # ~ sdata.operand0 = None
        return retVal

symbolTable = {}
def getSymbolMeta(id):
    c = symbolTable.get(id)
    if(c == None):
        if(id == '='):
            c = EqualsSymbol(id, 100)
        elif(id == '+'):
            c = PrefixInfixSymbol(id, 110, 130)
        elif(id == '-'):
            c = PrefixInfixSymbol(id, 110, 130)
        elif(id == '*'):
            c = InfixSymbol(id, 120)
        elif(id == '**'):
            c = InfixSymbol(id, 140)
        elif(id == '%'):
            c = InfixSymbol(id, 120)
        elif(id == '/'):
            c = InfixSymbol(id, 120)
        elif(id == '('):
            c = ParenthesisSymbol(id, 150)
        elif(id == '['):
            c = BracketSymbol(id, 150)
        elif(id == '{'):
            c = BraceSymbol(id, 150)
        elif(id == 'NAME'):
            c = NameSymbol(id, 0)
        elif(id == 'NUMBER'):
            c = NumberSymbol(id, 0)
        elif(id == 'END'):
            c = SymbolBase(id, 0)
        elif(id == ')'):
            c = SymbolBase(id, 0)
        elif(id == ']'):
            c = SymbolBase(id, 0)
        elif(id == '}'):
            c = SymbolBase(id, 0)
        elif(id == ','):
            c = SymbolBase(id, 0)
        symbolTable[id] = c
    return c

def getToken(expression, dataclass):
    TYPE_MAP = {tokenize.NUMBER: 'NUMBER', tokenize.STRING: 'STRING', \
        tokenize.OP: 'OPERATOR', tokenize.NAME: 'NAME'}
    COMMENT_MARKER = '#'

    ioprog = StringIO(expression)
    for t in tokenize.generate_tokens(lambda: next(ioprog)):
        try:
            if(len(t) == 1 or (len(t) > 1 and t[1]== '')):
                continue
            id, value = TYPE_MAP[t[0]], t[1]
        except KeyError:
            if(t[0] == tokenize.NL):
                continue
            if(t[0] == tokenize.ENDMARKER or t[1].startswith(COMMENT_MARKER)):
                break
            else:
                if(len(t) <= 1):
                    raise SyntaxError('Syntax error')
                else:
                    raise SyntaxError('Syntax error, unknown token: ' + t[1])

        if(id in {'NUMBER', 'NAME'}):
            meta = getSymbolMeta(id)
            sdata = dataclass(id, meta, value)
        else:
            meta = getSymbolMeta(value)
            if(meta == None):
                raise SyntaxError('Unknown operator (%r)' % value)
            sdata = dataclass(value, meta, None)
        yield sdata
    meta = getSymbolMeta('END')
    sdata = dataclass('END', meta, None)
    yield sdata

def parseExpression(precedence = 0):
    global _gNextData, _gtokenizer

    t = _gNextData
    _gNextData = next(_gtokenizer)

    left = t.getMetaData().procPrefix(t)
    while precedence < _gNextData.getMetaData().precedence:
        t = _gNextData
        _gNextData = next(_gtokenizer)
        left = t.getMetaData().procInfix(t, left)
    return left

# TODO: Get rid of globals
def parse(expression, dataclass):
    global _gNextData, _gtokenizer
    _gtokenizer = getToken(expression, dataclass)
    _gNextData = next(_gtokenizer)
    if(_gNextData.getMetaData().id == 'END'): # comment line
        return None
    return parseExpression()

