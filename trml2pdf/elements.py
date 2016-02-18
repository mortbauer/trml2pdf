from reportlab.platypus.flowables import KeepTogether, Spacer, _listWrapOn, _flowableSublist, PageBreak
from reportlab.platypus.doctemplate import FrameBreak
from reportlab.lib.utils import annotateException
from reportlab.platypus import tables
from reportlab.pdfgen.canvas import Canvas

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
        total_needed_width = 0
        for j,w in enumerate(W):
            if w is None:
                w = self._calcColumnWidth(j,spanRanges,colSpanCells,spanCons)
            if not isinstance(w,str):
                total_needed_width += w
            needed_widths.append(w)
        for j,w in enumerate(needed_widths):
            if isinstance(w,str):
                fac = float(w.rstrip('%'))/100
                W[j] = (availWidth-total_needed_width)*fac
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


class NumberedCanvas(Canvas):
    """
    special Canvas to have total page number available, take from: https://gist.github.com/k4ml/7061027
    """
    def __init__(self, *args, **kwargs):
        Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
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
