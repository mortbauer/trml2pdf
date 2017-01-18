import logging

from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import fonts
from reportlab.platypus import BaseDocTemplate, Paragraph
from reportlab.lib.sequencer import Sequencer
from reportlab.lib.utils import isSeq, encode_label, decode_label, annotateException, strTypes
from reportlab.platypus import doctemplate

from .elements import Anchor, Heading, TOCMixin, Ref

logger = logging.getLogger(__name__)

class DocTemplate(BaseDocTemplate):

    def afterInit(self):
        self.seq = Sequencer()
        self.levels = {}
        self.level_offset = None
        self.references = {}
        for i in range(6):
            self.seq.reset('Heading%s'%i)

    def beforeDocument(self):
        """ initializes the template

        by default create 6 TOC levels, if these are not enough more are added
        on the fly
        """
        self.canv.showOutline()

    def resolve_target(self,flowable):
        if flowable.target in self.references:
            flowable.resolve('.'.join(self.references[flowable.target]))

    def handle_flowable(self, flowables):
        """Detect Level 1 and 2 headings, build outline,
        and track chapter title."""
        flowable = flowables[0]
        if isinstance(flowable,TOCMixin):
            self.prepare_numbering_and_toc(flowable)
        elif isinstance(flowable,Ref):
            self.resolve_target(flowable)
        self._handle_flowable(flowables)

    def prepare_numbering_and_toc(self,flowable):
        level = None
        # automatically add numbering
        style_name = flowable.level
        if style_name.startswith('Heading'):
            level = int(style_name[7:])
        else:
            return
        if self.level_offset is None:
            self.level_offset = level -1
        if level - self.level_offset > 0:
            level -= self.level_offset
        flowable.toc_level = level
        if hasattr(flowable,'text'):
            text = flowable.text
        else:
            text = flowable
        if level is not None and not flowable._added_numbering:
            nums = []
            invalid_levels = False
            for i in range(level-1):
                cnt = int(self.seq.thisf('Heading%s'%(i+1)))
                if cnt == 0:
                    invalid_levels = True
                    break
                nums.append(str(cnt))
            if invalid_levels:
                logger.info('skipping numbering for %s',flowable.text)
            else:
                nums.append(str(self.seq.nextf('Heading%s'%level)))
                self.references[flowable.outline] = nums
                flowable.add_numbering(nums)
                for i in range(level,6):
                    key = 'Heading%s'%(i+1)
                    self.seq.reset(key)

    def afterFlowable(self, flowable):
        # handle bookmarks
        if isinstance(flowable,TOCMixin):
            if flowable._added_numbering:
                self.add_bookmark(flowable)
            elif hasattr(flowable,'key'):
                level = 0
                if flowable.toc:
                    entry = (level, flowable.toc, self.page, flowable.key)
                    self.notify('TOCEntry', entry)
                if flowable.outline:
                    self.canv.addOutlineEntry(flowable.outline, flowable.key, level, 0)

    def add_bookmark(self,flowable):
        key = 'sec%s'%('.'.join(flowable.nums))
        level = flowable.toc_level
        if hasattr(flowable,'style'):
            pos = self.frame._y+flowable.style.leading+flowable.style.spaceAfter
        else:
            pos = self.frame._y
        # outline
        self.canv.bookmarkPage(key,fit='XYZ',top=pos)
        if flowable.toc is not None:
            self.notify('TOCEntry', (level-1,flowable.toc, self.page, key))
        if flowable.outline is not None:
            self.canv.addOutlineEntry(flowable.outline, key, level-1, 0)

    def handle_frameEnd(self,resume=0):
        ''' Handles the semantics of the end of a frame. This includes the selection of
            the next frame or if this is the last frame then invoke pageEnd.
        '''
        self._removeVars(('frame',))
        self._leftExtraIndent = self.frame._leftExtraIndent
        self._rightExtraIndent = self.frame._rightExtraIndent
        self._frameBGs = self.frame._frameBGs
        f = self.frame
        print('frame end %s'%f.id)
        if hasattr(f,'lastFrame') or f is self.pageTemplate.frames[-1]:
            self.handle_pageEnd()
            self.frame = None
        else:
            if hasattr(self,'_nextFrameIndex'):
                next_frame = self.pageTemplate.frames[self._nextFrameIndex]
                del self._nextFrameIndex
            else:
                next_frame = self.pageTemplate.frames[self.pageTemplate.frames.index(f) + 1]
            if hasattr(next_frame,'init'):
                print('init frame %s with %s'%(next_frame.id,f.id))
                next_frame.init(f)
            self.frame = next_frame
            self.frame._debug = self._debug
            self.handle_frameBegin(resume)

    def handle_pageBegin(self):
        """Perform actions required at beginning of page.
        shouldn't normally be called directly"""
        self.page += 1
        logger.debug("beginning page %d" % self.page)
        print('old frames',[id(x) for x in self.pageTemplate.frames])
        # self.pageTemplate = self.pageTemplate.fresh_duplicate()
        self.pageTemplate.beforeDrawPage(self.canv,self)
        self.pageTemplate.checkPageSize(self.canv,self)
        self.pageTemplate.onPage(self.canv,self)
        print('new frames extraindent befor mod',[x._rightExtraIndent for x in self.pageTemplate.frames])
        for f in self.pageTemplate.frames: 
            f._reset()
        self.beforePage()
        #keep a count of flowables added to this page.  zero indicates bad stuff
        self._curPageFlowableCount = 0
        if hasattr(self,'_nextFrameIndex'):
            del self._nextFrameIndex
        self.frame = self.pageTemplate.frames[0]
        self.frame._debug = self._debug
        self.handle_frameBegin()
        print('new frames extraindent after mod',[x._rightExtraIndent for x in self.pageTemplate.frames])
        logger.debug('new frame extraindent is %s',self.frame._rightExtraIndent)

    def handle_documentBegin(self):
        '''implement actions at beginning of document'''
        self._hanging = [doctemplate.PageBegin]
        self.pageTemplate = self.pageTemplates[self._firstPageTemplateIndex].fresh_duplicate()
        self.page = 0
        self.beforeDocument()

    def _setPageTemplate(self):
        if hasattr(self,'_nextPageTemplateCycle'):
            #they are cycling through pages'; we keep the index
            self.pageTemplate = self._nextPageTemplateCycle.next_value
        elif hasattr(self,'_nextPageTemplateIndex'):
            self.pageTemplate = self.pageTemplates[self._nextPageTemplateIndex].fresh_duplicate()
            del self._nextPageTemplateIndex
        elif self.pageTemplate.autoNextPageTemplate:
            self.handle_nextPageTemplate(self.pageTemplate.autoNextPageTemplate)
            self.pageTemplate = self.pageTemplates[self._nextPageTemplateIndex].fresh_duplicate()
