import logging

from reportlab.platypus.flowables import *
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import fonts
from reportlab.platypus.doctemplate import BaseDocTemplate, ActionFlowable, FrameActionFlowable, _addGeneratedContent
from reportlab.lib.sequencer import Sequencer
from reportlab.lib.utils import isSeq, encode_label, decode_label, annotateException, strTypes
from reportlab.platypus import doctemplate

logger = logging.getLogger(__name__)


class DocTemplate(BaseDocTemplate):
    def get_numbering(self,level):
        nums = []
        for i in range(level):
            nums.append(str(int(self.seq.thisf(i))))
        return '.'.join(nums)

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
        
    def docEval(self,expr):
        try:
            return eval(expr.strip(),{},self._nameSpace)
        except:
            logger.exception('docEval failed')
            # exc = sys.exc_info()[1]
            # args = list(exc.args)
            # args[-1] += '\ndocEval %s failed!' % expr
            # exc.args = tuple(args)
            # raise

