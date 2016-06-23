from math import radians, cos, sin
from pdfrw import PdfReader
from pdfrw.buildxobj import pagexobj
from pdfrw.toreportlab import makerl

from reportlab.platypus.flowables import (
    _listWrapOn, _flowableSublist, PageBreak, _Container
)
from reportlab.lib.utils import annotateException, IdentStr, flatten, isStr, asNative, strTypes
from reportlab.platypus.doctemplate import FrameBreak
from reportlab.platypus import tableofcontents
from reportlab.lib.utils import annotateException
from reportlab.platypus import tables
from reportlab.platypus import flowables
from reportlab.platypus import xpreformatted
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Flowable
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.pdfdoc import PDFObjectReference

def _calc_pc(V,avail):
    '''check list V for percentage or * values
    1) absolute values go through unchanged
    2) percentages are used as weights for unconsumed space
    3) if no None values were seen '*' weights are
    set equally with unclaimed space
    otherwise * weights are assigned as None'''
    R = []
    r = R.append
    I = []
    i = I.append
    J = []
    j = J.append
    s = avail
    w = n = 0.
    for v in V:
        if isinstance(v,strTypes):
            v = str(v).strip()
            if not v:
                v = None
                n += 1
            elif v.endswith('%'):
                v = float(v[:-1])
                w += v
                i(len(R))
            elif v=='*':
                j(len(R))
            elif v=='min':
                j(len(R))
            else:
                v = float(v)
                s -= v
        elif v is None:
            n += 1
        else:
            s -= v
        r(v)
    s = max(0.,s)
    f = s/max(100.,w)
    for i in I:
        R[i] *= f
        s -= R[i]
    s = max(0.,s)
    m = len(J)
    if m:
        v =  n==0 and s/m or None
        for j in J:
            R[j] = v
    return R

tables._calc_pc = _calc_pc

class FloatToEnd(flowables.KeepTogether):
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
                 return [flowables.Spacer(aW,aH-H)]+self._content
             else:
                 S = self
                 S._state = 1
                 return [self._makeBreak(aH), S]
         else:
             if H>aH: return self._content
             return [flowables.Spacer(aW,aH-H)]+self._content

class Table(tables.Table):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self._user_col_widths = self._colWidths.copy()

    def _calcPreliminaryWidths(self, availWidth):
        """Fallback algorithm for when main one fails.

        Where exact width info not given but things like
        paragraphs might be present, do a preliminary scan
        and assign some best-guess values."""

        W = list(self._argW) # _calc_pc(self._argW,availWidth)
        verbose = 0
        totalDefined = 0.0
        percentDefined = 0
        percentTotal = 0
        numberUndefined = 0
        numberGreedyUndefined = 0
        for w in W:
            if w is None:
                numberUndefined += 1
            elif w == '*':
                numberUndefined += 1
                numberGreedyUndefined += 1
            elif w == 'min':
                numberUndefined += 1
                numberGreedyUndefined += 1
            elif tables._endswith(w,'%'):
                percentDefined += 1
                percentTotal += float(w[:-1])
            else:
                assert isinstance(w,(int,float))
                totalDefined = totalDefined + w

        #check columnwise in each None column to see if they are sizable.
        given = []
        sizeable = []
        unsizeable = []
        minimums = {}
        totalMinimum = 0
        for colNo in xrange(self._ncols):
            w = W[colNo]
            if w is None or w=='*' or w=='min' or tables._endswith(w,'%'):
                siz = 1
                final = 0
                for rowNo in xrange(self._nrows):
                    value = self._cellvalues[rowNo][colNo]
                    style = self._cellStyles[rowNo][colNo]
                    pad = style.leftPadding+style.rightPadding
                    new = self._elementWidth(value,style)
                    if new:
                        new += pad
                    else:
                        new = pad
                    new += style.leftPadding+style.rightPadding
                    final = max(final, new)
                    siz = siz and self._canGetWidth(value) # irrelevant now?
                if siz:
                    sizeable.append(colNo)
                else:
                    unsizeable.append(colNo)
                minimums[colNo] = final
                totalMinimum += final
            else:
                given.append(colNo)
        if len(given) == self._ncols:
            return

        # how much width is left:
        remaining = availWidth - (totalMinimum + totalDefined)
        if remaining > 0:
            # we have some room left; fill it.
            definedPercentage = (totalDefined/availWidth)*100
            percentTotal += definedPercentage
            if numberUndefined and percentTotal < 100:
                undefined = numberGreedyUndefined or numberUndefined
                defaultWeight = (100-percentTotal)/undefined
                percentTotal = 100
                defaultDesired = (defaultWeight/percentTotal)*availWidth
            else:
                defaultWeight = defaultDesired = 1
            # we now calculate how wide each column wanted to be, and then
            # proportionately shrink that down to fit the remaining available
            # space.  A column may not shrink less than its minimum width,
            # however, which makes this a bit more complicated.
            desiredWidths = []
            totalDesired = 0
            effectiveRemaining = remaining
            for colNo, minimum in minimums.items():
                w = W[colNo]
                if tables._endswith(w,'%'):
                    desired = (float(w[:-1])/percentTotal)*availWidth
                elif w == '*':
                    desired = defaultDesired
                elif w == 'min':
                    desired = minimum
                else:
                    desired = not numberGreedyUndefined and defaultDesired or 1
                if desired <= minimum:
                    W[colNo] = minimum
                else:
                    desiredWidths.append(
                        (desired-minimum, minimum, desired, colNo))
                    totalDesired += desired
                    effectiveRemaining += minimum
            if desiredWidths: # else we're done
                # let's say we have two variable columns.  One wanted
                # 88 points, and one wanted 264 points.  The first has a
                # minWidth of 66, and the second of 55.  We have 71 points
                # to divide up in addition to the totalMinimum (i.e.,
                # remaining==71).  Our algorithm tries to keep the proportion
                # of these variable columns.
                #
                # To do this, we add up the minimum widths of the variable
                # columns and the remaining width.  That's 192.  We add up the
                # totalDesired width.  That's 352.  That means we'll try to
                # shrink the widths by a proportion of 192/352--.545454.
                # That would make the first column 48 points, and the second
                # 144 points--adding up to the desired 192.
                #
                # Unfortunately, that's too small for the first column.  It
                # must be 66 points.  Therefore, we go ahead and save that
                # column width as 88 points.  That leaves (192-88==) 104
                # points remaining.  The proportion to shrink the remaining
                # column is (104/264), which, multiplied  by the desired
                # width of 264, is 104: the amount assigned to the remaining
                # column.
                proportion = effectiveRemaining/totalDesired
                # we sort the desired widths by difference between desired and
                # and minimum values, a value called "disappointment" in the
                # code.  This means that the columns with a bigger
                # disappointment will have a better chance of getting more of
                # the available space.
                desiredWidths.sort()
                finalSet = []
                for disappointment, minimum, desired, colNo in desiredWidths:
                    adjusted = proportion * desired
                    if adjusted < minimum:
                        W[colNo] = minimum
                        totalDesired -= desired
                        effectiveRemaining -= minimum
                        if totalDesired:
                            proportion = effectiveRemaining/totalDesired
                    else:
                        finalSet.append((minimum, desired, colNo))
                for minimum, desired, colNo in finalSet:
                    adjusted = proportion * desired
                    assert adjusted >= minimum
                    W[colNo] = adjusted
        else:
            for colNo, minimum in minimums.items():
                W[colNo] = minimum
        if verbose: print('new widths are:', W)
        self._argW = self._colWidths = W
        return W

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

    def _calc(self, availWidth, availHeight):
        #if hasattr(self,'_width'): return

        #in some cases there are unsizable things in
        #cells.  If so, apply a different algorithm
        #and assign some withs in a less (thanks to Gary Poster) dumb way.
        #this CHANGES the widths array.
        if (None in self._colWidths or '*' in self._colWidths or 'min' in self._colWidths) and self._hasVariWidthElements():
            W = self._calcPreliminaryWidths(availWidth) #widths
        else:
            W = None

        # need to know which cells are part of spanned
        # ranges, so _calc_height and _calc_width can ignore them
        # in sizing
        if self._spanCmds:
            self._calcSpanRanges()
            if None in self._argH:
                self._calc_width(availWidth,W=W)

        if self._nosplitCmds:
            self._calcNoSplitRanges()

        # calculate the full table height
        self._calc_height(availHeight,availWidth,W=W)

        # calculate the full table width
        self._calc_width(availWidth,W=W)

        if self._spanCmds:
            #now work out the actual rect for each spanned cell from the underlying grid
            self._calcSpanRects()

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
        elif tables._isLineCommand(cmd):
            # we expect op, start, stop, weight, colour, cap, dashes, join
            cmd = list(cmd)
            if len(cmd)<5: raise ValueError('bad line command '+str(cmd))

            #determine line cap value at position 5. This can be str or numeric.
            if len(cmd)<6:
                cmd.append(1)
            else:
                cap = tables._convert2int(cmd[5], tables.LINECAPS, 0, 2, 'cap', cmd)
                cmd[5] = cap

            #dashes at index 6 - this is a dash array:
            if len(cmd)<7: cmd.append(None)

            #join mode at index 7 - can be str or numeric, look up as for caps
            if len(cmd)<8: cmd.append(1)
            else:
                join = tables._convert2int(cmd[7], tables.LINEJOINS, 0, 2, 'join', cmd)
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
                    tables._setCellStyle(self._cellStyles, i, j, op, values)

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

    def bookmarkPage(self, key,
                      fit="Fit",
                      left=None,
                      top=None,
                      bottom=None,
                      right=None,
                      zoom=None
                      ):
        """
        This creates a bookmark to the current page which can
        be referred to with the given key elsewhere.

        PDF offers very fine grained control over how Acrobat
        reader is zoomed when people link to this. The default
        is to keep the user's current zoom settings. the last
        arguments may or may not be needed depending on the
        choice of 'fitType'.

        Fit types and the other arguments they use are:

        - XYZ left top zoom - fine grained control.  null
          or zero for any of the parameters means 'leave
          as is', so "0,0,0" will keep the reader's settings.
          NB. Adobe Reader appears to prefer "null" to 0's.

        - Fit - entire page fits in window

        - FitH top - top coord at top of window, width scaled
          to fit.

        - FitV left - left coord at left of window, height
          scaled to fit

        - FitR left bottom right top - scale window to fit
          the specified rectangle

        (question: do we support /FitB, FitBH and /FitBV
        which are hangovers from version 1.1 / Acrobat 3.0?)"""
        dest = self._bookmarkReference(key)
        self._doc.inPage() # try to enable page-only features
        pageref = self.thisPageRef()

        #None = "null" for PDF
        if left is None:
            left = "null"
        if top is None:
            top = "null"
        if bottom is None:
            bottom = "null"
        if right is None:
            right = "null"
        if zoom is None:
            zoom = "null"

        if fit == "XYZ":
            dest.xyz(left,top,zoom)
        elif fit == "Fit":
            dest.fit()
        elif fit == "FitH":
            dest.fith(top)
        elif fit == "FitV":
            dest.fitv(left)
        elif fit == "FitR":
            dest.fitr(left,bottom,right,top)
        #Do we need these (version 1.1 / Acrobat 3 versions)?
        elif fit == "FitB":
            dest.fitb()
        elif fit == "FitBH":
            dest.fitbh(top)
        elif fit == "FitBV":
            dest.fitbv(left)
        else:
            raise ValueError("Unknown Fit type %s" % ascii(fit))

        dest.setPage(pageref)
        return dest

    def thisPageRef(self):
        return PDFObjectReference('Page%s'%self.getPageNumber())

    def showPage(self):
        data = dict(self.__dict__)
        self._saved_page_states.append(data)
        self._startPage()

    def save(self):
        """add page info to each page (page x of y)"""
        from lxml import etree
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            for count, _code in enumerate(state['_code']):
                if isinstance(_code,tuple):
                    TYPE,canv,element = _code
                    canv._totalpagecount = num_pages
                    container = etree.Element('container')
                    container.append(element)
                    canv.render(container)
                    state['_code'][count] = canv.canvas._code.pop()
            self.__dict__.update(state)
            super().showPage()
        super().save()

class PdfPage(Flowable):
    _fixedWidth = 1
    """PdfImage wraps the first page from a PDF file as a Flowable
    which can be included into a ReportLab Platypus document.
    Based on the vectorpdf extension in rst2pdf (http://code.google.com/p/rst2pdf/)
    """
    def __init__(self, pdfpage, width=None, height=None, kind='direct',hAlign='LEFT',rotation=0):
        # If using StringIO buffer, set pointer to begining
        self.xobj = pagexobj(pdfpage)
        self.rotation = rotation
        self.imageWidth = width
        self.imageHeight = height
        x1, y1, x2, y2 = self.xobj.BBox
        self.hAlign = hAlign

        w, h = x2 - x1, y2 - y1
        self._w = abs(w * cos(radians(rotation)) + h * sin(radians(rotation)))
        self._h = abs(w * sin(radians(rotation)) + h * cos(radians(rotation)))
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
        x_ = x * cos(radians(self.rotation)) + (y+self.drawWidth) * sin(radians(self.rotation))
        y_ = x * sin(radians(self.rotation)) + y * cos(radians(self.rotation))

        canv.saveState()
        canv.translate(x_, y_)
        canv.rotate(self.rotation)
        canv.scale(xscale, yscale)
        canv.doForm(xobj_name)
        canv.restoreState()

class Anchor(flowables.Spacer):
    '''create a bookmark in the pdf'''
    _ZEROSIZE=1
    _SPACETRANSFER = True
    def __init__(self,name,level):
        super().__init__(0,0)
        self._bookmark_name = name
        self._bookmark_class = level
        self._level = level

    def __repr__(self):
        return "%s(%s)" % (self.__class__.__name__,self._bookmark_name)

    def wrap(self,aW,aH):
        return 0,0

    def draw(self):
        pass

class TableOfContents(tableofcontents.TableOfContents):
    """This creates a formatted table of contents.

    It presumes a correct block of data is passed in.
    The data block contains a list of (level, text, pageNumber)
    triplets.  You can supply a paragraph style for each level
    (starting at zero).
    Set dotsMinLevel to determine from which level on a line of
    dots should be drawn between the text and the page number.
    If dotsMinLevel is set to a negative value, no dotted lines are drawn.
    """

    def __init__(self,**kwds):
        self.rightColumnWidth = kwds.pop('rightColumnWidth',72)
        self.levelStyles = kwds.pop('levelStyles',tableofcontents.defaultLevelStyles)
        self.tableStyle = kwds.pop('tableStyle',tableofcontents.defaultTableStyle)
        self.dotsMinLevel = kwds.pop('dotsMinLevel',1)
        self.formatter = kwds.pop('formatter',None)
        if kwds: raise ValueError('unexpected keyword arguments %s' % ', '.join(kwds.keys()))
        if len(self.levelStyles) < 1:
            self.levelStyles = tableofcontents.defaultLevelStyles
        self._table = None
        self._entries = []
        self._lastEntries = []

class XPreformatted(xpreformatted.XPreformatted):
    def minWidth(self):
        w = 0
        for frag in self.frags:
            w += stringWidth(frag.text,frag.fontName,frag.fontSize)
        return w
