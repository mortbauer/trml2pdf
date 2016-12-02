#!/usr/bin/python
# -*- coding: utf-8 -*-

# trml2pdf - An RML to PDF converter
# Copyright (C) 2003, Fabien Pinckaers, UCL, FSA
# Contributors
#     Richard Waid <richard@iopen.net>
#     Klaas Freitag <freitag@kde.org>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import copy
import os
import io
import sys
import logging

from lxml import etree
import click
from reportlab import platypus
from reportlab.platypus import para
import reportlab
from reportlab.pdfgen import canvas
from pdfrw import PdfReader

from . import color
from . import utils
from .elements import FloatToEnd, Table, NumberedCanvas, PdfPage, Anchor, TableOfContents, XPreformatted, Heading, Ref

logger = logging.getLogger(__name__)

def _child_get(node, childs):
    clds = []
    for n in node:
        if n.tag == childs:
            clds.append(n)
    return clds


class RMLStyles(object):

    def __init__(self, nodes):
        self.styles = copy.deepcopy(reportlab.lib.styles.getSampleStyleSheet().byName)
        self.names = {}
        self.table_styles = {}
        self.list_styles = {}
        for node in nodes:
            for style in node.xpath('blockTableStyle'):
                self.table_styles[style.attrib['id']] = self._table_style_get(style)
            for style in node.xpath('listStyle'):
                self.list_styles[style.attrib['name']] = self._list_style_get(style)
            for style in node.xpath('paraStyle'):
                self.styles[style.attrib['name']] = self._para_style_get(style)
            for variable in node.xpath('initialize'):
                for name in variable.xpath('name'):
                    self.names[name.attrib['id']] = name.attrib['value']

    def _para_style_update(self, style, node):
        for attr in ['textColor', 'backColor', 'bulletColor','borderColor']:
            if attr in node.attrib:
                style.__dict__[attr] = color.get(node.attrib[attr])
        for attr in ['fontName', 'bulletFontName', 'bulletText']:
            if attr in node.attrib:
                style.__dict__[attr] = node.attrib[attr]
        for attr in ['borderWidth','borderRadius','fontSize', 'leftIndent', 'rightIndent', 'spaceBefore', 'spaceAfter', 'firstLineIndent', 'bulletIndent', 'bulletFontSize', 'leading']:
            if attr in node.attrib:
                if attr == 'fontSize' and not 'leading' in node.attrib:
                    style.__dict__['leading'] = utils.unit_get(node.attrib[attr]) * 1.2
                style.__dict__[attr] = utils.unit_get(node.attrib[attr])
        if 'alignment' in node.attrib:
            align = {
                'right': reportlab.lib.enums.TA_RIGHT,
                'center': reportlab.lib.enums.TA_CENTER,
                'justify': reportlab.lib.enums.TA_JUSTIFY
            }
            style.alignment = align.get(
                node.attrib['alignment'].lower(), reportlab.lib.enums.TA_LEFT)
        return style

    def _list_style_update(self, style, node):
        for attr in ['bulletColor']:
            if attr in node.attrib:
                style.__dict__[attr] = color.get(node.attrib.get(attr,''))
        for attr in ['bulletType', 'bulletFontName', 'bulletDetent', 'bulletDir', 'bulletFormat', 'start']:
            if attr in node.attrib:
                style.__dict__[attr] = node.attrib.get(attr)
        for attr in ['leftIndent', 'rightIndent', 'bulletFontSize', 'bulletOffsetY']:
            if attr in node.attrib:
                style.__dict__[attr] = utils.unit_get(node.attrib.get(attr))
        if 'bulletAlign' in node.attrib:
            align = {
                'right': reportlab.lib.enums.TA_RIGHT,
                'center': reportlab.lib.enums.TA_CENTER,
                'justify': reportlab.lib.enums.TA_JUSTIFY
            }
            style.alignment = align.get(
                node.attrib.get('alignment').lower(), reportlab.lib.enums.TA_LEFT)
        return style

    @staticmethod
    def _table_style_get(style_node):
        styles = []
        for node in style_node:
            start = utils.tuple_int_get(node, 'start', (0, 0))
            stop = utils.tuple_int_get(node, 'stop', (-1, -1))
            if node.tag == 'blockValign':
                styles.append(
                    ('VALIGN', start, stop, str(node.attrib.get('value'))))
            elif node.tag == 'blockFont':
                styles.append(
                    ('FONT', start, stop, str(node.attrib.get('name'))))
            elif node.tag == 'blockSpan':
                if 'byCol' in node.attrib:
                    each = int(node.attrib.get('byCol'))
                    styles.append(('COLSPAN',start, stop,each))
                elif 'byRow' in node.attrib:
                    each = int(node.attrib.get('byRow'))
                    styles.append(('ROWSPAN',start, stop,each))
                else:
                    styles.append(('SPAN', start, stop))
            elif node.tag == 'blockTextColor':
                styles.append(
                    ('TEXTCOLOR', start, stop, color.get(str(node.attrib.get('colorName','')))))
            elif node.tag == 'blockLeading':
                styles.append(
                    ('LEADING', start, stop, utils.unit_get(node.attrib.get('length'))))
            elif node.tag == 'blockAlignment':
                styles.append(
                    ('ALIGNMENT', start, stop, str(node.attrib.get('value'))))
            elif node.tag == 'blockLeftPadding':
                styles.append(
                    ('LEFTPADDING', start, stop, utils.unit_get(node.attrib.get('length'))))
            elif node.tag == 'blockRightPadding':
                styles.append(
                    ('RIGHTPADDING', start, stop, utils.unit_get(node.attrib.get('length'))))
            elif node.tag == 'blockTopPadding':
                styles.append(
                    ('TOPPADDING', start, stop, utils.unit_get(node.attrib.get('length'))))
            elif node.tag == 'blockBottomPadding':
                styles.append(
                    ('BOTTOMPADDING', start, stop, utils.unit_get(node.attrib.get('length'))))
            elif node.tag == 'blockBackground':
                if 'colorName' in node.attrib:
                    styles.append(
                        ('BACKGROUND', start, stop, color.get(node.attrib.get('colorName',''))))
                if 'colorsByRow' in node.attrib:
                    colors = [color.get(x) for x in node.attrib.get('colorsByRow','').split(';')]
                    styles.append(
                        ('ROWBACKGROUNDS', start, stop,colors ))
                if 'colorsByCol' in node.attrib:
                    colors = [color.get(x) for x in node.attrib.get('colorsByCol','').split(';')]
                    styles.append(
                        ('COLBACKGROUNDS', start, stop,colors ))
            if 'size' in node.attrib:
                styles.append(
                    ('FONTSIZE', start, stop, utils.unit_get(node.attrib.get('size'))))
            elif node.tag == 'lineStyle':
                kind = node.attrib.get('kind')
                kind_list = ['GRID', 'BOX', 'OUTLINE', 'INNERGRID',
                                'LINEBELOW', 'LINEABOVE', 'LINEBEFORE', 'LINEAFTER']
                assert kind in kind_list
                thick = 1
                if 'thickness' in node.attrib:
                    thick = float(node.attrib.get('thickness'))
                styles.append(
                    (kind, start, stop, thick, color.get(node.attrib.get('colorName',''))))
        return platypus.tables.TableStyle(styles)

    def _list_style_get(self, node):
        style = reportlab.lib.styles.ListStyle('Default')
        if "parent" in node.attrib:
            parent = node.attrib.get("parent")
            parentStyle = self.styles.get(parent)
            if not parentStyle:
                raise Exception("parent style = '%s' not found" % parent)
            style.__dict__.update(parentStyle.__dict__)
            style.alignment = parentStyle.alignment
        self._list_style_update(style, node)
        return style

    def _para_style_get(self, node):
        if "parent" in node.attrib:
            parent = node.attrib['parent']
            style = copy.deepcopy(self.styles[parent])
        else:
            style = copy.deepcopy(self.styles["Normal"])
        style.name = node.attrib['name']
        self._para_style_update(style, node)
        return style

    def para_style_get(self, node):
        style = False
        if 'style' in node.attrib:
            stylename = node.attrib.get('style')
            if stylename in self.styles:
                style = copy.deepcopy(self.styles[stylename])
            else:
                logger.warn('style %s not found, setting default',stylename)
        if not style:
            styles = reportlab.lib.styles.getSampleStyleSheet()
            style = copy.deepcopy(styles['Normal'])
        return self._para_style_update(style, node)


class RMLDoc(object):

    def __init__(self, data):
        self.root = etree.fromstring(data)
        # remove comments
        for comment in self.root.xpath('//comment()'):
            parent = comment.getparent()
            if parent is not None:
                parent.remove(comment)
        self.filename = self.root.get('filename')

    def docinit(self, els):
        from reportlab.lib.fonts import addMapping
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        for node in els:
            for font in node.xpath('registerFont'):
                name = font.attrib.get('fontName')
                fname = font.attrib.get('fontFile')
                pdfmetrics.registerFont(TTFont(name, fname))
                addMapping(name, 0, 0, name)  # normal
                addMapping(name, 0, 1, name)  # italic
                addMapping(name, 1, 0, name)  # bold
                addMapping(name, 1, 1, name)  # italic and bold

    def render(self, out, DocTmpl=None):
        el = self.root.xpath('docinit')
        if el:
            self.docinit(el)

        el = self.root.xpath('stylesheet')
        self.styles = RMLStyles(el)

        el = self.root.xpath('template')
        if len(el):
            pt_obj = RMLTemplate(out, el[0], self,DocTmpl=DocTmpl)
            pt_obj.render(self.root.xpath('story')[0])
        else:
            self.canvas = canvas.Canvas(out)
            pd = self.root.xpath('pageDrawing')[0]
            pd_obj = RMLCanvas(self.canvas, None, self)
            pd_obj.render(pd)
            self.canvas.showPage()
            self.canvas.save()


class RMLCanvas(object):

    def __init__(self, canvas, doc_tmpl=None, doc=None):
        self.canvas = canvas
        self.styles = doc.styles
        self.doc_tmpl = doc_tmpl
        self.doc = doc
        self._totalpagecount = None

    def _textual(self, node):
        nnode = etree.Element(node.tag,**node.attrib)
        if node.text is None:
            nnode.text = ''
        else:
            nnode.text = copy.deepcopy(node.text)
        for n in node:
            if n.tag == 'pageNumber':
                nnode.text += str(self.canvas.getPageNumber())
            elif n.tag == 'totalPageNumber':
                if self._totalpagecount is None:
                    nnode.append(copy.deepcopy(n))
                else:
                    nnode.text += str(self._totalpagecount)
            if n.tail:
                nnode.text += n.tail
        return nnode

    def _drawString(self, node):
        nnode = self._textual(node)
        if len(nnode) == 0:
            self.canvas.drawString(
                text=nnode.text, **utils.attr_get(node, ['x', 'y']))
        else:
            self.canvas._code.append(('POSTPONED',self,nnode))

    def _drawCenteredString(self, node):
        nnode = self._textual(node)
        if len(nnode) == 0:
            self.canvas.drawCentredString(
                text=nnode.text, **utils.attr_get(node, ['x', 'y']))
        else:
            self.canvas._code.append(('POSTPONED',self,nnode))

    def _drawRightString(self, node):
        nnode = self._textual(node)
        if len(nnode) == 0:
            self.canvas.drawRightString(
                text=nnode.text, **utils.attr_get(node, ['x', 'y']))
        else:
            self.canvas._code.append(('POSTPONED',self,nnode))

    def _rect(self, node):
        if 'round' in node.attrib:
            self.canvas.roundRect(
                radius=utils.unit_get(node.attrib.get('round')),
                **utils.attr_get(node, ['x', 'y', 'width', 'height'], {'fill': 'bool', 'stroke': 'bool'})
            )
        else:
            self.canvas.rect(
                **utils.attr_get(node, ['x', 'y', 'width', 'height'], {'fill': 'bool', 'stroke': 'bool'}))

    def _ellipse(self, node):
        x1 = utils.unit_get(node.attrib.get('x'))
        x2 = utils.unit_get(node.attrib.get('width'))
        y1 = utils.unit_get(node.attrib.get('y'))
        y2 = utils.unit_get(node.attrib.get('height'))
        self.canvas.ellipse(
            x1, y1, x2, y2, **utils.attr_get(node, [], {'fill': 'bool', 'stroke': 'bool'}))

    def _curves(self, node):
        line_str = utils.text_get(node).split()

        while len(line_str) > 7:
            self.canvas.bezier(*[utils.unit_get(l) for l in line_str[0:8]])
            line_str = line_str[8:]

    def _lines(self, node):
        line_str = utils.text_get(node).split()
        lines = []
        while len(line_str) > 3:
            lines.append([utils.unit_get(l) for l in line_str[0:4]])
            line_str = line_str[4:]
        self.canvas.lines(lines)

    def _grid(self, node):
        xlist = [utils.unit_get(s) for s in node.attrib.get('xs').split(',')]
        ylist = [utils.unit_get(s) for s in node.attrib.get('ys').split(',')]
        self.canvas.grid(xlist, ylist)

    def _translate(self, node):
        dx = 0
        dy = 0
        if 'dx' in node.attrib:
            dx = utils.unit_get(node.attrib.get('dx'))
        if 'dy' in node.attrib:
            dy = utils.unit_get(node.attrib.get('dy'))
        self.canvas.translate(dx, dy)

    def _circle(self, node):
        self.canvas.circle(
            x_cen=utils.unit_get(node.attrib.get('x')),
            y_cen=utils.unit_get(node.attrib.get('y')),
            r=utils.unit_get(node.attrib.get('radius')),
            **utils.attr_get(node, [], {'fill': 'bool', 'stroke': 'bool'})
        )

    def _place(self, node):
        flows = RMLFlowable(self.doc).render(node)
        infos = utils.attr_get(node, ['x', 'y', 'width', 'height'])

        infos['y'] += infos['height']
        for flow in flows:
            w, h = flow.wrap(infos['width'], infos['height'])
            if w <= infos['width'] and h <= infos['height']:
                infos['y'] -= h
                flow.drawOn(self.canvas, infos['x'], infos['y'])
                infos['height'] -= h
            else:
                raise ValueError("Not enough space")

    def _line_mode(self, node):
        ljoin = {'round': 1, 'mitered': 0, 'bevelled': 2}
        lcap = {'default': 0, 'round': 1, 'square': 2}
        if 'width' in node.attrib:
            self.canvas.setLineWidth(
                utils.unit_get(node.attrib.get('width')))
        if 'join' in node.attrib:
            self.canvas.setLineJoin(ljoin[node.attrib.get('join')])
        if 'cap' in node.attrib:
            self.canvas.setLineCap(lcap[node.attrib.get('cap')])
        if 'miterLimit' in node.attrib:
            self.canvas.setDash(
                utils.unit_get(node.attrib.get('miterLimit')))
        if 'dash' in node.attrib:
            dashes = node.attrib.get('dash').split(',')
            for x in range(len(dashes)):
                dashes[x] = utils.unit_get(dashes[x])
            self.canvas.setDash(node.attrib.get('dash').split(','))

    def _image(self, node):
        from six.moves import urllib
        from reportlab.lib.utils import ImageReader
        try:
            u = urllib.request.urlopen("file:" + str(node.attrib.get('file')))
        except:
            # TODO
            logger.warn('couldn\'t find image at: %s',node.attrib.get('file'))
            return
        s = io.BytesIO()
        s.write(u.read())
        s.seek(0)
        img = ImageReader(s)
        (sx, sy) = img.getSize()

        args = {}
        for tag in ('width', 'height', 'x', 'y'):
            if tag in node.attrib:
                # if not utils.unit_get(node.attrib.get(tag)):
                #     continue
                args[tag] = utils.unit_get(node.attrib.get(tag))

        args['mask'] = node.get('mask','auto')
        if "preserveAspectRatio" in node.attrib:
            args["preserveAspectRatio"] = True
        if ('width' in args) and ('height' not in args):
            args['height'] = sy * args['width'] / sx
        elif ('height' in args) and ('width' not in args):
            args['width'] = sx * args['height'] / sy
        elif ('width' in args) and ('height' in args) and (not args.get("preserveAspectRatio", False)):
            if (float(args['width']) / args['height']) > (float(sx) > sy):
                args['width'] = sx * args['height'] / sy
            else:
                args['height'] = sy * args['width'] / sx
        if 'showBoundary' in node and node.attrib.get('showBoundary'):
            self.canvas.rect(args['x'],args['y'],args['width'],args['height'])
        self.canvas.drawImage(img, **args)

    def _barcode(self, node):
        from reportlab.graphics.barcode import code128, qr

        createargs = {}
        drawargs = {}
        code_type = node.attrib.get('code')
        for tag in ('x', 'y'):
            if tag in node.attrib:
                drawargs[tag] = utils.unit_get(node.attrib.get(tag))

        if code_type == 'Code128':
            for tag in ('barWidth', 'barHeight'):
                if tag in node.attrib:
                    createargs[tag] = utils.unit_get(node.attrib.get(tag))
            barcode = code128.Code128(self._textual(node), **createargs)
        elif code_type == "QR":
            for tag in ('width', 'height'):
                if tag in node.attrib:
                    createargs[tag] = utils.unit_get(node.attrib.get(tag))
            barcode = qr.QrCode(node.attrib.get('value'), **createargs)

        barcode.drawOn(self.canvas, **drawargs)

    def _path(self, node):
        self.path = self.canvas.beginPath()
        self.path.moveTo(**utils.attr_get(node, ['x', 'y']))
        for n in node:
            if n.nodeType == node.ELEMENT_NODE:
                if n.tag == 'moveto':
                    vals = utils.text_get(n).split()
                    self.path.moveTo(
                        utils.unit_get(vals[0]), utils.unit_get(vals[1]))
                elif n.tag == 'curvesto':
                    vals = utils.text_get(n).split()
                    while len(vals) > 5:
                        pos = []
                        while len(pos) < 6:
                            pos.append(utils.unit_get(vals.pop(0)))
                        self.path.curveTo(*pos)
            elif (n.nodeType == node.TEXT_NODE):
                # Not sure if I must merge all TEXT_NODE ?
                data = n.data.split()
                while len(data) > 1:
                    x = utils.unit_get(data.pop(0))
                    y = utils.unit_get(data.pop(0))
                    self.path.lineTo(x, y)
        if (not 'close' in node) or utils.bool_get(node.attrib.get('close')):
            self.path.close()
        self.canvas.drawPath(
            self.path, **utils.attr_get(node, [], {'fill': 'bool', 'stroke': 'bool'}))

    def _stroke(self,node):
        self.canvas.setStrokeColor(color.get(node.attrib.get('color','')))
        if 'width' in node.attrib:
            self.canvas.setLineWidth(float(node.attrib.get('width')))

    def render(self, node):
        tags = {
            'drawCentredString': self._drawCenteredString,
            'drawCenteredString': self._drawCenteredString,
            'drawRightString': self._drawRightString,
            'drawString': self._drawString,
            'rect': self._rect,
            'ellipse': self._ellipse,
            'lines': self._lines,
            'grid': self._grid,
            'curves': self._curves,
            'fill': lambda node: self.canvas.setFillColor(color.get(node.attrib.get('color',''))),
            'stroke':self._stroke,
            'setFont': lambda node: self.canvas.setFont(node.attrib.get('name'), utils.unit_get(node.attrib.get('size'))),
            'place': self._place,
            'circle': self._circle,
            'lineMode': self._line_mode,
            'path': self._path,
            'rotate': lambda node: self.canvas.rotate(float(node.attrib.get('degrees'))),
            'translate': self._translate,
            'image': self._image,
            'barCode': self._barcode,
        }
        for nd in node:
            if nd.tag in tags:
                tags[nd.tag](nd)
            else:
                logger.warn('unknown tag {}'.format(nd.tag))


class RMLDraw(object):

    def __init__(self, node, styles):
        self.node = node
        self.styles = styles
        self.canvas = None

    def render(self, canvas, doc):
        canvas.saveState()
        cnv = RMLCanvas(canvas, doc, self.styles)
        cnv.render(self.node)
        canvas.restoreState()


class RMLFlowable(object):

    def __init__(self, doc):
        self.doc = doc
        self.styles = doc.styles

    def _textual(self, node):
        rc = node.text
        for n in node:
            if n.tag == 'getName':
                newNode = self.doc.dom.createTextNode(
                    self.styles.names.get(n.attrib.get('id'), 'Unknown name'))
                node.insertBefore(newNode, n)
                node.removeChild(n)
            elif n.tag == 'pageNumber':
                rc += '<pageNumber/>'  # TODO: change this !
            else:
                rc += self._textual(n)
        return rc

    def _list(self, node):
        if 'style' in node.attrib:
            list_style = self.styles.list_styles[node.attrib.get('style')]
        else:
            list_style = platypus.flowables.ListStyle('Default')

        list_items = []
        for li in _child_get(node, 'li'):
            flow = []
            for n in li:
                for flowable in self._flowable(n):
                    if flowable is not None:
                        flow.append(flowable)
            if not flow:
                if 'style' in li.attrib:
                    li_style = self.styles.styles[
                        li.attrib.get('style')]
                else:
                    li_style = reportlab.lib.styles.getSampleStyleSheet()[
                        'Normal']
                flow = para.Paragraph(self._textual(li), li_style)
            list_item = platypus.ListItem(flow)
            list_items.append(list_item)
        kwargs = {}
        for key in ('bulletType',):
            if key in node.attrib:
                kwargs[key] = node.attrib.get(key)
        return platypus.ListFlowable(list_items, style=list_style, start=list_style.__dict__.get('start'),**kwargs)

    def _table(self, node):
        length = 0
        colwidths = None
        rowheights = None
        data = []
        style = None
        for style_node in node.xpath('blockTableStyle'):
            style = RMLStyles._table_style_get(style_node)
        for tr in _child_get(node, 'tr'):
            columns = []
            for td in _child_get(tr, 'td'):
                flow = []
                for n in td:
                    for flowable in self._flowable(n):
                        if flowable is not None:
                            flow.append(flowable)
                if not len(flow):
                    flow = self._textual(td)
                columns.append(flow)
            if len(columns) > length:
                length = len(columns)
                for ab in data:
                    while len(ab) < length:
                        ab.append('')
            while len(columns) < length:
                columns.append('')
            data.append(columns)
        if 'colWidths' in node.attrib:
            colwidths = [
                utils.unit_get(f.strip()) for f in node.attrib.get('colWidths').split(',')]
        if 'rowHeights' in node.attrib:
            value = node.attrib.get('rowHeights')
            if ',' in value:
                rowheights = [utils.unit_get(f.strip()) for f in value.split(',')]
            else:
                rowheights = utils.unit_get(value.strip())
        table = Table(data=data, colWidths=colwidths, rowHeights=rowheights, **(
            utils.attr_get(
                node, ['splitByRow','spaceBefore','spaceAfter'],
                {'repeatRows': 'int', 'repeatCols': 'int','hAlign':'str','vAlign':'str'})
        ))
        if 'style' in node.attrib:
            stylename = node.attrib.get('style')
            if stylename in self.styles.table_styles:
                style = self.styles.table_styles[stylename]
            else:
                logger.warn('style %s not found',stylename)
        if style is not None:
            table.setStyle(style)
        return table

    def _illustration(self, node):
        class Illustration(platypus.flowables.Flowable):
            def __init__(self, node, styles):
                self.node = node
                self.styles = styles
                self.width = utils.unit_get(node.attrib.get('width'))
                self.height = utils.unit_get(node.attrib.get('height'))

            def wrap(self, *args):
                return (self.width, self.height)

            def draw(self):
                canvas = self.canv
                drw = RMLDraw(self.node, self.styles)
                drw.render(self.canv, None)
        return Illustration(node, self.styles)

    def _floattoend(self,node):
        content = []
        for child in node:
            for flow in self._flowable(child):
                if flow is not None:
                    content.append(flow)
        return FloatToEnd(content)

    def _keeptogether(self,node):
        content = []
        for child in node:
            for flow in self._flowable(child):
                if flow is not None:
                    content.append(flow)
        return platypus.KeepTogether(content)

    def _serialize_paragraph_content(self,node):
        parts = []
        for child in node:
            parts.append(etree.tostring(child).decode('utf-8'))
        res = ''.join(parts)
        if node.text:
            return ''.join((node.text,res))
        else:
            return res

    def _get_para_options(self,node):
        d = {}
        d['alignment'] = node.attrib.get('alignment')
        d['fontName'] = node.attrib.get('fontName')
        d['fontSize'] = node.attrib.get('fontSize')
        d['leading'] = node.attrib.get('leading')
        d['leftIndent'] = node.attrib.get('leftIndent')
        d['rightIndent'] = node.attrib.get('rightIndent')
        d['spaceBefore'] = node.attrib.get('spaceBefore')
        d['spaceAfter'] = node.attrib.get('spaceAfter')
        return d

    def _flowable(self, node):
        if node.tag == 'para':
            style = self.styles.para_style_get(node)
            yield platypus.Paragraph(self._serialize_paragraph_content(node), style)
        elif node.tag == 'ref':
            style = self.styles.para_style_get(node)
            yield Ref(node.attrib.get('target'),style)
        elif node.tag == 'toc':
            styles = []
            style_names = node.attrib.get('levelStyles','')
            for style_name in style_names.split(','):
                styles.append(self.styles.styles[style_name])
            toc = TableOfContents(levelStyles=styles)
            yield toc
        elif node.tag == 'name':
            self.styles.names[
                node.attrib.get('id')] = node.attrib.get('value')
            yield None
        elif node.tag == 'xpre':
            style = self.styles.para_style_get(node)
            raw = self._serialize_paragraph_content(node)
            yield XPreformatted(raw, style, **(utils.attr_get(node, [], {'bulletText': 'str', 'dedent': 'int', 'frags': 'int'})))
        elif node.tag == 'pre':
            style = self.styles.para_style_get(node)
            text = self._textual(node)
            yield platypus.Preformatted(text, style, **(utils.attr_get(node, [], {'bulletText': 'str', 'dedent': 'int'})))
        elif node.tag == 'illustration':
            yield self._illustration(node)
        elif node.tag == 'blockTable':
            yield self._table(node)
        elif node.tag == 'floatToEnd':
            yield self._floattoend(node)
        elif node.tag == 'keepTogether':
            yield self._keeptogether(node)
        elif node.tag == 'title':
            style = copy.deepcopy(self.styles.styles['Title'])
            self.styles._para_style_update(style,node)
            yield platypus.Paragraph(self._textual(node), style, **(utils.attr_get(node, [], {'bulletText': 'str'})))
        elif node.tag == 'h1':
            style = copy.deepcopy(self.styles.styles['Heading1'])
            self.styles._para_style_update(style,node)
            yield Heading(
                self._textual(node),
                style,
                short=node.attrib.get('short'),
                toc=node.attrib.get('toc'),
                outline=node.attrib.get('outline'),
            )
        elif node.tag == 'h2':
            style = copy.deepcopy(self.styles.styles['Heading2'])
            self.styles._para_style_update(style,node)
            yield Heading(
                self._textual(node),
                style,
                short=node.attrib.get('short'),
                toc=node.attrib.get('toc'),
                outline=node.attrib.get('outline'),
            )
        elif node.tag == 'h3':
            style = copy.deepcopy(self.styles.styles['Heading3'])
            self.styles._para_style_update(style,node)
            yield Heading(
                self._textual(node),
                style,
                short=node.attrib.get('short'),
                toc=node.attrib.get('toc'),
                outline=node.attrib.get('outline'),
            )
        elif node.tag == 'h4':
            style = copy.deepcopy(self.styles.styles['Heading4'])
            self.styles._para_style_update(style,node)
            yield Heading(
                self._textual(node),
                style,
                short=node.attrib.get('short'),
                toc=node.attrib.get('toc'),
                outline=node.attrib.get('outline'),
            )
        elif node.tag == 'h5':
            style = copy.deepcopy(self.styles.styles['Heading5'])
            self.styles._para_style_update(style,node)
            yield Heading(
                self._textual(node),
                style,
                short=node.attrib.get('short'),
                toc=node.attrib.get('toc'),
                outline=node.attrib.get('outline'),
            )
        elif node.tag == 'h6':
            style = copy.deepcopy(self.styles.styles['Heading6'])
            self.styles._para_style_update(style,node)
            yield Heading(
                self._textual(node),
                style,
                short=node.attrib.get('short'),
                toc=node.attrib.get('toc'),
                outline=node.attrib.get('outline'),
            )
        elif node.tag == 'image':
            attrs = utils.attr_get(node, ['width', 'height', 'kind', 'hAlign','mask','lazy'])
            if 'mask' not in attrs:
                attrs['mask'] = (250, 255, 250, 255, 250, 255)
            yield platypus.Image(
                node.attrib.get('file'),**attrs)
        elif node.tag == 'bookmark':
            yield Anchor(
                node.attrib.get('key'),
                short=node.attrib.get('short'),
                toc=node.attrib.get('tox'),
                outline=node.attrib.get('outline'),
                level=node.attrib.get('level'),
            )
        elif node.tag == 'pdfpage':
            page_number = node.attrib.get('page')
            if not page_number:
                page_number = 0
            else:
                page_number = int(page_number)
            page = PdfReader(node.attrib.get('file'), decompress=False).pages[page_number]
            yield PdfPage(page, **(utils.attr_get(node, ['width', 'height', 'kind','hAlign','rotation'])))
        elif node.tag == 'pdfpages':
            wrapper = node.attrib.get('wrapper')
            pdf = PdfReader(node.attrib.get('file'), decompress=False)
            options = utils.attr_get(node, ['width', 'height', 'kind','hAlign','rotation'])
            if wrapper:
                Wrapper = globals()[wrapper]
                for page in pdf.pages:
                    yield Wrapper(PdfPage(page,**options))
            else:
                for page in pdf.pages:
                    yield PdfPage(page,**options)

        elif node.tag == 'spacer':
            if 'width' in node.attrib:
                width = utils.unit_get(node.attrib.get('width'))
            else:
                width = utils.unit_get('1cm')
            length = utils.unit_get(node.attrib.get('length'))
            yield platypus.Spacer(width=width, height=length)
        elif node.tag == 'barCode':
            yield code39.Extended39(self._textual(node))
        elif node.tag == 'pageBreak':
            yield platypus.PageBreak()
        elif node.tag == 'condPageBreak':
            yield platypus.CondPageBreak(**(utils.attr_get(node, ['height'])))
        elif node.tag == 'setNextTemplate':
            yield platypus.NextPageTemplate(str(node.attrib.get('name')))
        elif node.tag == 'nextFrame':
            yield platypus.CondPageBreak(1000)  # TODO: change the 1000 !
        elif node.tag == 'ul':
            yield self._list(node)
        elif node.tag == 'hr':
            kw = {}
            if 'thickness' in node.attrib:
                kw['thickness'] = utils.unit_get(node.attrib.get('thickness'))
            if 'spaceBefore' in node.attrib:
                kw['spaceBefore'] = utils.unit_get(node.attrib.get('spaceBefore'))
            if 'spaceAfter' in node.attrib:
                kw['spaceAfter'] = utils.unit_get(node.attrib.get('spaceAfter'))
            if 'color' in node.attrib:
                kw['color'] = color.get(node.attrib.get('color',''))
            if 'width' in node.attrib:
                kw['width'] = node.attrib.get('width')
            if 'dash' in node.attrib:
                kw['dash'] = node.attrib.get('dash')
            if 'hAlign' in node.attrib:
                kw['hAlign'] = node.attrib.get('hAlign')
            if 'cAlign' in node.attrib:
                kw['cAlign'] = node.attrib.get('cAlign')
            yield platypus.flowables.HRFlowable(**kw)
        elif node.tag == 'indent':
            from reportlab.platypus.paraparser import _num
            kw = {}
            for key in ('left','right'):
                if key in node.attrib:
                    kw[key] = _num(node.attrib.get(key))
            yield platypus.Indenter(**kw)
            for child in node:
                for flow in self._flowable(child):
                    yield flow
            yield platypus.Indenter(**{x:-1*y for x,y in kw.items()})
        elif node.tag.endswith('Template'):
            pass
        else:
            logger.warn('flowable "%s" not yet implemented',node.tag)
            yield None

    def render(self, node_story):
        story = []
        for element in node_story:
            for flow in self._flowable(element):
                if flow:
                    story.append(flow)
        return story


class RMLTemplate(object):

    def __init__(self, out, node, doc, DocTmpl=None):
        if 'pageSize' not in node.attrib:
            pageSize = (utils.unit_get('21cm'), utils.unit_get('29.7cm'))
        else:
            ps = [x.strip() for x in node.attrib['pageSize'].replace(')', '').replace(
                '(', '').split(',')]
            pageSize = (utils.unit_get(ps[0]), utils.unit_get(ps[1]))
        attributes = utils.attr_get(
            node,
            attrs=['leftMargin', 'rightMargin', 'topMargin', 'bottomMargin'],
            attrs_dict={
                'allowSplitting': 'int',
                'showBoundary': 'bool',
                'title': 'str',
                'author': 'str',
                'subject': 'str',
                'application': 'str',
                'rotation': 'int'})
        if DocTmpl is None:
            self.doc_tmpl = platypus.BaseDocTemplate(out, pagesize=pageSize, **attributes)
        else:
            self.doc_tmpl = DocTmpl(out, pagesize=pageSize, **attributes)
        self.page_templates = []
        self.doc = doc
        pts = doc.root.xpath('//pageTemplate')
        frame_args = ['x1', 'y1', 'width', 'height', 'leftPadding', 'rightPadding', 'bottomPadding', 'topPadding']
        frame_kwargs = {'id': 'text', 'showBoundary': 'bool'}
        for pt in pts:
            frames = []
            for frame_el in pt.xpath('frame'):
                attribs = utils.attr_get(frame_el, frame_args, frame_kwargs)
                frame = platypus.Frame(**attribs)
                frames.append(frame)
            gr = pt.xpath('pageGraphics')
            if len(gr):
                drw = RMLDraw(gr[0], self.doc)
                self.page_templates.append(platypus.PageTemplate(
                    frames=frames, onPage=drw.render, **utils.attr_get(pt, [], {'id': 'str'})))
            else:
                self.page_templates.append(
                    platypus.PageTemplate(frames=frames, **utils.attr_get(pt, [], {'id': 'str'})))
        self.doc_tmpl.addPageTemplates(self.page_templates)

    def render(self, node_story):
        r = RMLFlowable(self.doc)
        fis = r.render(node_story)
        self.doc_tmpl.multiBuild(fis,canvasmaker=NumberedCanvas)


@click.command()
@click.option('-l','--log-level',default='WARNING')
@click.argument('fromfile')
@click.option('-o','--tofile')
def main(fromfile,tofile,log_level):
    logger.setLevel(log_level)
    from_path = os.path.abspath(fromfile)
    with open(from_path,'rb') as i:
        r = RMLDoc(i.read())
    if tofile is None:
        to_path = '%s.pdf'%os.path.splitext(fromfile)[0]
    else:
        to_path = os.path.abspath(tofile)
    with open(to_path,'wb') as o:
        r.render(o)


if __name__ == "__main__":
    main()
