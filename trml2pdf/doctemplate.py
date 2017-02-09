import logging

from reportlab.pdfgen import canvas
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

    def _startBuild(self, filename=None, canvasmaker=canvas.Canvas):
        self._calc()

        #each distinct pass gets a sequencer
        self.seq = Sequencer()

        self.canv = canvasmaker(filename or self.filename,
                                pagesize=self.pagesize,
                                invariant=self.invariant,
                                pageCompression=self.pageCompression,
                                enforceColorSpace=self.enforceColorSpace,
                                )

        getattr(self.canv,'setEncrypt',lambda x: None)(self.encrypt)

        self.canv._cropMarks = self.cropMarks
        self.canv.setAuthor(self.author)
        self.canv.setTitle(self.title)
        self.canv.setSubject(self.subject)
        self.canv.setCreator(self.creator)
        self.canv.setKeywords(self.keywords)
        self.canv._doc.info.custom_metadata = self.custom_metadata

        if self.displayDocTitle is not None:
            self.canv.setViewerPreference('DisplayDocTitle',['false','true'][self.displayDocTitle])
        if self.lang:
            self.canv.setCatalogEntry('Lang',self.lang)

        if self._onPage:
            self.canv.setPageCallBack(self._onPage)
        self.handle_documentBegin()
