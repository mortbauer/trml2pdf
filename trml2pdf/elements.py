from reportlab.platypus.flowables import KeepTogether, Spacer, _listWrapOn, _flowableSublist, PageBreak
from reportlab.platypus.doctemplate import FrameBreak

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



