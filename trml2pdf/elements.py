from pdfrw import PdfReader
from pdfrw.buildxobj import pagexobj
from pdfrw.toreportlab import makerl

from reportlab.platypus.flowables import (
    KeepTogether, Spacer, _listWrapOn, _flowableSublist, PageBreak, _Container
)
from reportlab.platypus.tables import (
    _isLineCommand, _convert2int, _setCellStyle, LINECAPS, LINEJOINS,
)
from reportlab.platypus.doctemplate import FrameBreak
from reportlab.lib.utils import annotateException
from reportlab.platypus import tables
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Flowable
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.pdfbase.pdfmetrics import stringWidth

class FloatToEnd(KeepTogether):
     '''
     Float some flowables to the end of the current frame
     from: http://comments.gmane.org/gmane.comp.python.reportlab.user/9234
     '''
     def __init__(self,flowables,maxHeight=None,brk='frame'):
         self._content = _flowableSublist(flowables)
         self._maxHeight = maxHeight
         self._state = 0
         self._brk = brk

     def wrap(self,aW,aH):
         return aW,aH+1  #force a split

     def _makeBreak(self,h):
         if self._brk=='page':
             return PageBreak()
         else:
             return FrameBreak

     def split(self,aW,aH):
         dims = []
         W,H = _listWrapOn(self._content,aW,self.canv,dims=dims)
         if self._state==0:
             if H<aH:
                 return [Spacer(aW,aH-H)]+self._content
             else:
                 S = self
                 S._state = 1
                 return [self._makeBreak(aH), S]
         else:
             if H>aH: return self._content
             return [Spacer(aW,aH-H)]+self._content

class Table(tables.Table):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self._user_col_widths = self._colWidths.copy()

    def _elementWidth(self,v,s):
        if isinstance(v,(list,tuple)):
            w = 0
            for e in v:
                ew = self._elementWidth(e,s)
                if ew is None: return None
                w = max(w,ew)
            return w
        elif isinstance(v,Flowable) and v._fixedWidth:
            if hasattr(v, 'width') and isinstance(v.width,(int,float)): return v.width
            if hasattr(v, 'drawWidth') and isinstance(v.drawWidth,(int,float)): return v.drawWidth
        # Even if something is fixedWidth, the attribute to check is not
        # necessarily consistent (cf. Image.drawWidth).  Therefore, we'll
        # be extra-careful and fall through to this code if necessary.
        if hasattr(v, 'minWidth'):
            try:
                w = v.minWidth() # should be all flowables
                if isinstance(w,(float,int)): return w
            except AttributeError:
                pass
        if isinstance(v,str):
            return stringWidth(v,s.fontname,s.fontsize)
        else:
            return 0

    def _calcColumnWidth(self,j,spanRanges,colSpanCells,spanCons):
        V = self._cellvalues
        S = self._cellStyles
        w = 0
        for i,Vi in enumerate(V):
            v = Vi[j]
            s = S[i][j]
            ji = j,i
            span = spanRanges.get(ji,None)
            if ji in colSpanCells and not span: #if the current cell is part of a spanned region,
                t = 0.0                         #assume a zero size.
            else:#work out size
                t = self._elementWidth(v,s)
                if t is None:
                    raise ValueError("Flowable %s in cell(%d,%d) can't have auto width\n%s" % (v.identity(30),i,j,self.identity(30)))
                t += s.leftPadding+s.rightPadding
                if span:
                    c0 = span[0]
                    c1 = span[2]
                    if c0!=c1:
                        x = c0,c1
                        spanCons[x] = max(spanCons.get(x,t),t)
                        t = 0
            if t>w: w = t   #record a new maximum
        return w

    def _calc_width(self,availWidth,W=None):
        if getattr(self,'_width_calculated_once',None): return
        #comments added by Andy to Robin's slightly terse variable names
        if not W: W = self._argW
        # if not W: W = _calc_pc(self._argW,availWidth)   #widths array
        canv = getattr(self,'canv',None)
        saved = None
        if self._spanCmds:
            colSpanCells = self._colSpanCells
            spanRanges = self._spanRanges
        else:
            colSpanCells = ()
            spanRanges = {}
        spanCons = {}
        if W is self._argW:
            W0 = W
            W = W[:]
        else:
            W0 = W[:]
        V = self._cellvalues
        S = self._cellStyles
        # calc minimal needed widths
        needed_widths = []
        for j,w in enumerate(W):
            if w is None:
                w = self._calcColumnWidth(j,spanRanges,colSpanCells,spanCons)
            needed_widths.append(w)
        for j,w in enumerate(needed_widths):
            if isinstance(w,str):
                fac = float(w.rstrip('%'))/100
                tables.spanFixDim(W0,W,spanCons,lim=j-1)
                W[j] = (availWidth-sum(W[:j]))*fac
            else:
                W[j] = w
        if spanCons:
            try:
                tables.spanFixDim(W0,W,spanCons)
            except:
                annotateException('\nspanning problem in %s\nW0=%r W=%r\nspanCons=%r' % (self.identity(),W0,W,spanCons))

        self._colWidths = W
        width = 0
        self._colpositions = [0]        #index -1 is right side boundary; we skip when processing cells
        for w in W:
            width = width + w
            self._colpositions.append(width)

        self._width = width
        self._width_calculated_once = 1

    def _addCommand(self,cmd):
        if cmd[0] in ('BACKGROUND','ROWBACKGROUNDS','COLBACKGROUNDS'):
            self._bkgrndcmds.append(cmd)
        elif cmd[0] in ('SPAN','ROWSPAN','COLSPAN'):
            self._spanCmds.append(cmd)
        elif cmd[0] == 'NOSPLIT':
            # we expect op, start, stop
            self._nosplitCmds.append(cmd)
        elif _isLineCommand(cmd):
            # we expect op, start, stop, weight, colour, cap, dashes, join
            cmd = list(cmd)
            if len(cmd)<5: raise ValueError('bad line command '+str(cmd))

            #determine line cap value at position 5. This can be str or numeric.
            if len(cmd)<6:
                cmd.append(1)
            else:
                cap = _convert2int(cmd[5], LINECAPS, 0, 2, 'cap', cmd)
                cmd[5] = cap

            #dashes at index 6 - this is a dash array:
            if len(cmd)<7: cmd.append(None)

            #join mode at index 7 - can be str or numeric, look up as for caps
            if len(cmd)<8: cmd.append(1)
            else:
                join = _convert2int(cmd[7], LINEJOINS, 0, 2, 'join', cmd)
                cmd[7] = join

            #linecount at index 8.  Default is 1, set to 2 for double line.
            if len(cmd)<9: cmd.append(1)
            else:
                lineCount = cmd[8]
                if lineCount is None:
                    lineCount = 1
                    cmd[8] = lineCount
                assert lineCount >= 1
            #linespacing at index 9. Not applicable unless 2+ lines, defaults to line
            #width so you get a visible gap between centres
            if len(cmd)<10: cmd.append(cmd[3])
            else:
                space = cmd[9]
                if space is None:
                    space = cmd[3]
                    cmd[9] = space
            assert len(cmd) == 10

            self._linecmds.append(tuple(cmd))
        else:
            (op, (sc, sr), (ec, er)), values = cmd[:3] , cmd[3:]
            if sc < 0: sc = sc + self._ncols
            if ec < 0: ec = ec + self._ncols
            if sr < 0: sr = sr + self._nrows
            if er < 0: er = er + self._nrows
            for i in xrange(sr, er+1):
                for j in xrange(sc, ec+1):
                    _setCellStyle(self._cellStyles, i, j, op, values)

    def _calcSpanRanges(self):
        """Work out rects for tables which do row and column spanning.

        This creates some mappings to let the later code determine
        if a cell is part of a "spanned" range.
        self._spanRanges shows the 'coords' in integers of each
        'cell range', or None if it was clobbered:
        (col, row) -> (col0, row0, col1, row1)

        Any cell not in the key is not part of a spanned region
        """
        self._spanRanges = spanRanges = {}
        for x in xrange(self._ncols):
            for y in xrange(self._nrows):
                spanRanges[x,y] = (x, y, x, y)
        self._colSpanCells = []
        self._rowSpanCells = []
        csa = self._colSpanCells.append
        rsa = self._rowSpanCells.append
        for args in self._spanCmds:
            x0, y0 = args[1]
            x1, y1 = args[2]

            #normalize
            if x0 < 0: x0 = x0 + self._ncols
            if x1 < 0: x1 = x1 + self._ncols
            if y0 < 0: y0 = y0 + self._nrows
            if y1 < 0: y1 = y1 + self._nrows
            if x0 > x1: x0, x1 = x1, x0
            if y0 > y1: y0, y1 = y1, y0

            if x0!=x1 or y0!=y1:
                if x0!=x1: #column span
                    for y in xrange(y0, y1+1):
                        for x in xrange(x0,x1+1):
                            csa((x,y))
                if y0!=y1: #row span
                    for y in xrange(y0, y1+1):
                        for x in xrange(x0,x1+1):
                            rsa((x,y))

                for y in xrange(y0, y1+1):
                    for x in xrange(x0,x1+1):
                        spanRanges[x,y] = None
                # set the main entry
                if args[0] == 'SPAN':
                    spanRanges[x0,y0] = (x0, y0, x1, y1)
                elif args[0] == 'COLSPAN':
                    for i in xrange(x0,x1+1,args[3]):
                        spanRanges[i,y0] = (i, y0, i+args[3]-1, y1)
                elif args[0] == 'ROWSPAN':
                    for i in xrange(y0,y1+1,args[3]):
                        spanRanges[x0,i] = (x0, i, x1, i+args[3]-1)

class NumberedCanvas(Canvas):
    """
    special Canvas to have total page number available, take from: https://gist.github.com/k4ml/7061027
    """
    def __init__(self, *args, **kwargs):
        Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        data = dict(self.__dict__)
        self._saved_page_states.append(data)
        self._startPage()

    def save(self):
        """add page info to each page (page x of y)"""
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            for count, _code in enumerate(state['_code']):
                state['_code'][count] = state['_code'][count].replace('{TOTAL_PAGE_COUNT}', str(num_pages))
            self.__dict__.update(state)
            Canvas.showPage(self)
        Canvas.save(self)

class PdfPage(Flowable):
    _fixedWidth = 1
    """PdfImage wraps the first page from a PDF file as a Flowable
    which can be included into a ReportLab Platypus document.
    Based on the vectorpdf extension in rst2pdf (http://code.google.com/p/rst2pdf/)
    """
    def __init__(self, pdfpage, width=None, height=None, kind='direct',hAlign='LEFT'):
        # If using StringIO buffer, set pointer to begining
        self.xobj = pagexobj(pdfpage)
        self.imageWidth = width
        self.imageHeight = height
        x1, y1, x2, y2 = self.xobj.BBox
        self.hAlign = hAlign

        self._w, self._h = x2 - x1, y2 - y1
        if not self.imageWidth:
            self.imageWidth = self._w
        if not self.imageHeight:
            self.imageHeight = self._h
        self.__ratio = float(self.imageWidth)/self.imageHeight
        if kind in ['direct','absolute'] or width==None or height==None:
            self.drawWidth = width or self.imageWidth
            self.drawHeight = height or self.imageHeight
        elif kind in ['bound','proportional']:
            factor = min(float(width)/self._w,float(height)/self._h)
            self.drawWidth = self._w*factor
            self.drawHeight = self._h*factor

    def wrap(self, aW, aH):
        return self.drawWidth, self.drawHeight

    def drawOn(self, canv, x, y, _sW=0):
        if _sW > 0 and hasattr(self, 'hAlign'):
            a = self.hAlign
            if a in ('CENTER', 'CENTRE', TA_CENTER):
                x += 0.5*_sW
            elif a in ('RIGHT', TA_RIGHT):
                x += _sW
            elif a not in ('LEFT', TA_LEFT):
                raise ValueError("Bad hAlign value " + str(a))

        xobj = self.xobj
        xobj_name = makerl(canv._doc, xobj)

        xscale = self.drawWidth/self._w
        yscale = self.drawHeight/self._h

        x -= xobj.BBox[0] * xscale
        y -= xobj.BBox[1] * yscale

        canv.saveState()
        canv.translate(x, y)
        canv.scale(xscale, yscale)
        canv.doForm(xobj_name)
        canv.restoreState()
