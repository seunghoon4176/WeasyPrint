#!/usr/bin/env python3
"""
Mini WeasyPrint - 경량 HTML to PDF 변환기
단일 파일로 구성된 WeasyPrint 축소판 (Windows 최적화)

기본 의존성만 사용:
- reportlab: PDF 생성
- html.parser: HTML 파싱 (내장)
- re: CSS 파싱 (내장)

사용법:
    python mini_weasyprint.py input.html output.pdf
    
    # 또는 Python 코드에서:
    from mini_weasyprint import MiniWeasyPrint
    converter = MiniWeasyPrint()
    converter.html_to_pdf('<h1>Hello World!</h1>', 'output.pdf')
"""

import re
import sys
import argparse
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from pathlib import Path
import base64

try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib.units import inch
    from reportlab.lib.colors import Color, black, red, blue, green
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import os
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    print("경고: reportlab이 설치되지 않았습니다. 설치하려면: pip install reportlab")

class CSSParser:
    """간단한 CSS 파서"""
    
    def __init__(self):
        self.styles = {}
    
    def parse_css(self, css_text):
        """CSS 텍스트를 파싱하여 스타일 딕셔너리 생성"""
        # CSS 주석 제거
        css_text = re.sub(r'/\*.*?\*/', '', css_text, flags=re.DOTALL)
        
        # CSS 규칙 추출
        rules = re.findall(r'([^{}]+)\s*\{([^{}]+)\}', css_text)
        
        for selector, declarations in rules:
            selector = selector.strip()
            style_dict = {}
            
            # 선언 파싱
            declarations = declarations.split(';')
            for decl in declarations:
                if ':' in decl:
                    prop, value = decl.split(':', 1)
                    style_dict[prop.strip()] = value.strip()
            
            self.styles[selector] = style_dict
        
        return self.styles
    
    def get_style(self, tag, class_name=None, tag_id=None):
        """태그에 해당하는 스타일 반환"""
        style = {}
        
        # 태그 스타일
        if tag in self.styles:
            style.update(self.styles[tag])
        
        # 클래스 스타일
        if class_name:
            class_selector = f'.{class_name}'
            if class_selector in self.styles:
                style.update(self.styles[class_selector])
        
        # ID 스타일
        if tag_id:
            id_selector = f'#{tag_id}'
            if id_selector in self.styles:
                style.update(self.styles[id_selector])
        
        return style

class HTMLElement:
    """HTML 요소를 표현하는 클래스"""
    
    def __init__(self, tag, attrs=None, content=''):
        self.tag = tag
        self.attrs = attrs or {}
        self.content = content
        self.children = []
        self.parent = None
        self.style = {}
    
    def add_child(self, child):
        child.parent = self
        self.children.append(child)
    
    def get_text(self):
        """요소의 모든 텍스트 반환"""
        text = self.content
        for child in self.children:
            text += child.get_text()
        return text

class MiniHTMLParser(HTMLParser):
    """경량 HTML 파서"""
    
    def __init__(self):
        super().__init__()
        self.document = HTMLElement('document')
        self.current_element = self.document
        self.element_stack = [self.document]
    
    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        element = HTMLElement(tag, attrs_dict)
        self.current_element.add_child(element)
        
        # 자체 닫는 태그가 아닌 경우 스택에 추가
        if tag not in ['br', 'hr', 'img', 'input', 'meta', 'link']:
            self.element_stack.append(element)
            self.current_element = element
    
    def handle_endtag(self, tag):
        if len(self.element_stack) > 1 and self.current_element.tag == tag:
            self.element_stack.pop()
            self.current_element = self.element_stack[-1]
    
    def handle_data(self, data):
        if data.strip():
            text_element = HTMLElement('text', content=data.strip())
            self.current_element.add_child(text_element)

class MiniWeasyPrint:
    """경량 WeasyPrint 메인 클래스"""
    
    def __init__(self):
        self.css_parser = CSSParser()
        self.html_parser = MiniHTMLParser()
        self.page_size = A4
        self.margin = 72  # 1인치
        self.korean_font_registered = False
        
        # 한글 폰트 등록 시도
        self._register_korean_fonts()
        
        # 기본 스타일
        font_name = 'NanumGothic' if self.korean_font_registered else 'Helvetica'
        self.default_styles = {
            'h1': {'font-size': '24pt', 'font-weight': 'bold', 'margin-bottom': '12pt', 'font-name': font_name},
            'h2': {'font-size': '20pt', 'font-weight': 'bold', 'margin-bottom': '10pt', 'font-name': font_name},
            'h3': {'font-size': '16pt', 'font-weight': 'bold', 'margin-bottom': '8pt', 'font-name': font_name},
            'h4': {'font-size': '14pt', 'font-weight': 'bold', 'margin-bottom': '6pt', 'font-name': font_name},
            'h5': {'font-size': '12pt', 'font-weight': 'bold', 'margin-bottom': '4pt', 'font-name': font_name},
            'h6': {'font-size': '10pt', 'font-weight': 'bold', 'margin-bottom': '2pt', 'font-name': font_name},
            'p': {'font-size': '12pt', 'margin-bottom': '6pt', 'font-name': font_name},
            'div': {'font-size': '12pt', 'font-name': font_name},
            'span': {'font-size': '12pt', 'font-name': font_name},
        }
    
    def _register_korean_fonts(self):
        """한글 폰트 등록"""
        if not REPORTLAB_AVAILABLE:
            return
        
        # 윈도우 시스템 폰트 경로들
        windows_font_paths = [
            r"C:\Windows\Fonts\malgun.ttf",      # 맑은 고딕
            r"C:\Windows\Fonts\gulim.ttc",       # 굴림
            r"C:\Windows\Fonts\batang.ttc",      # 바탕
            r"C:\Windows\Fonts\NanumGothic.ttf", # 나눔고딕 (있다면)
        ]
        
        for font_path in windows_font_paths:
            if os.path.exists(font_path):
                try:
                    if font_path.endswith('malgun.ttf'):
                        pdfmetrics.registerFont(TTFont('NanumGothic', font_path))
                        print(f"한글 폰트 등록 성공: 맑은 고딕 ({font_path})")
                        self.korean_font_registered = True
                        break
                    elif font_path.endswith('gulim.ttc'):
                        pdfmetrics.registerFont(TTFont('NanumGothic', font_path))
                        print(f"한글 폰트 등록 성공: 굴림 ({font_path})")
                        self.korean_font_registered = True
                        break
                    elif font_path.endswith('batang.ttc'):
                        pdfmetrics.registerFont(TTFont('NanumGothic', font_path))
                        print(f"한글 폰트 등록 성공: 바탕 ({font_path})")
                        self.korean_font_registered = True
                        break
                    elif font_path.endswith('NanumGothic.ttf'):
                        pdfmetrics.registerFont(TTFont('NanumGothic', font_path))
                        print(f"한글 폰트 등록 성공: 나눔고딕 ({font_path})")
                        self.korean_font_registered = True
                        break
                except Exception as e:
                    print(f"폰트 등록 실패 {font_path}: {e}")
                    continue
        
        if not self.korean_font_registered:
            print("경고: 한글 폰트를 찾을 수 없습니다. 한글이 제대로 표시되지 않을 수 있습니다.")
            print("해결 방법: 나눔폰트나 다른 한글 TTF 폰트를 시스템에 설치하세요.")
    
    def parse_html(self, html_content):
        """HTML 파싱"""
        # CSS 추출
        css_matches = re.findall(r'<style[^>]*>(.*?)</style>', html_content, re.DOTALL | re.IGNORECASE)
        for css in css_matches:
            self.css_parser.parse_css(css)
        
        # HTML 파싱
        self.html_parser = MiniHTMLParser()
        self.html_parser.feed(html_content)
        
        return self.html_parser.document
    
    def apply_styles(self, element):
        """요소에 스타일 적용"""
        # 기본 스타일
        if element.tag in self.default_styles:
            element.style.update(self.default_styles[element.tag])
        
        # CSS 스타일
        class_name = element.attrs.get('class')
        element_id = element.attrs.get('id')
        css_style = self.css_parser.get_style(element.tag, class_name, element_id)
        element.style.update(css_style)
        
        # 자식 요소에도 재귀적으로 적용
        for child in element.children:
            self.apply_styles(child)
    
    def create_pdf_content(self, document, pdf_canvas):
        """PDF 내용 생성"""
        if not REPORTLAB_AVAILABLE:
            raise ImportError("reportlab이 필요합니다: pip install reportlab")
        
        # SimpleDocTemplate 사용하여 문서 생성
        doc = SimpleDocTemplate(
            "temp.pdf",
            pagesize=self.page_size,
            rightMargin=self.margin,
            leftMargin=self.margin,
            topMargin=self.margin,
            bottomMargin=self.margin
        )
        
        # 스타일 시트
        styles = getSampleStyleSheet()
        story = []
        
        self._add_elements_to_story(document, story, styles)
        
        return story
    
    def _add_elements_to_story(self, element, story, styles):
        """요소를 PDF story에 추가"""
        if element.tag == 'text':
            # 텍스트 요소는 부모 컨텍스트에서 처리
            return element.content
        
        elif element.tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            # 헤더 요소
            level = int(element.tag[1])
            style_name = f'Heading{level}' if level <= 6 else 'Heading6'
            text = self._get_element_text(element)
            if text:
                # 한글 폰트가 등록된 경우 스타일 수정
                if self.korean_font_registered:
                    korean_style = ParagraphStyle(
                        name=f'Korean{style_name}',
                        parent=styles[style_name],
                        fontName='NanumGothic',
                        fontSize=styles[style_name].fontSize,
                        leading=styles[style_name].fontSize * 1.2
                    )
                    para = Paragraph(text, korean_style)
                else:
                    para = Paragraph(text, styles[style_name])
                story.append(para)
                story.append(Spacer(1, 12))
        
        elif element.tag == 'p':
            # 단락 요소
            text = self._get_element_text(element)
            if text:
                # 한글 폰트가 등록된 경우 스타일 수정
                if self.korean_font_registered:
                    korean_style = ParagraphStyle(
                        name='KoreanNormal',
                        parent=styles['Normal'],
                        fontName='NanumGothic',
                        fontSize=12,
                        leading=14
                    )
                    para = Paragraph(text, korean_style)
                else:
                    para = Paragraph(text, styles['Normal'])
                story.append(para)
                story.append(Spacer(1, 6))
        
        elif element.tag == 'br':
            # 줄바꿈
            story.append(Spacer(1, 12))
        
        elif element.tag == 'hr':
            # 수평선
            story.append(Spacer(1, 6))
            # 간단한 선 그리기 (reportlab의 다른 방법 필요)
            story.append(Spacer(1, 6))
        
        else:
            # 기타 요소는 자식 요소들을 처리
            for child in element.children:
                self._add_elements_to_story(child, story, styles)
    
    def _get_element_text(self, element):
        """요소의 모든 텍스트 내용 반환"""
        text_parts = []
        
        if element.tag == 'text':
            return element.content
        
        for child in element.children:
            if child.tag == 'text':
                text_parts.append(child.content)
            else:
                child_text = self._get_element_text(child)
                if child_text:
                    # 간단한 HTML 태그 처리
                    if child.tag == 'strong' or child.tag == 'b':
                        text_parts.append(f'<b>{child_text}</b>')
                    elif child.tag == 'em' or child.tag == 'i':
                        text_parts.append(f'<i>{child_text}</i>')
                    else:
                        text_parts.append(child_text)
        
        return ' '.join(text_parts)
    
    def html_to_pdf(self, html_content, output_path):
        """HTML을 PDF로 변환"""
        if not REPORTLAB_AVAILABLE:
            print("오류: reportlab이 설치되지 않았습니다.")
            print("설치 방법: pip install reportlab")
            return False
        
        try:
            # HTML 파싱
            document = self.parse_html(html_content)
            
            # 스타일 적용
            self.apply_styles(document)
            
            # PDF 생성
            doc = SimpleDocTemplate(
                output_path,
                pagesize=self.page_size,
                rightMargin=self.margin,
                leftMargin=self.margin,
                topMargin=self.margin,
                bottomMargin=self.margin
            )
            
            styles = getSampleStyleSheet()
            story = []
            
            self._add_elements_to_story(document, story, styles)
            
            # PDF 빌드
            doc.build(story)
            
            print(f"PDF가 성공적으로 생성되었습니다: {output_path}")
            return True
            
        except Exception as e:
            print(f"PDF 생성 중 오류 발생: {e}")
            return False
    
    def html_file_to_pdf(self, html_file_path, output_path):
        """HTML 파일을 PDF로 변환"""
        try:
            with open(html_file_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            return self.html_to_pdf(html_content, output_path)
        except Exception as e:
            print(f"HTML 파일 읽기 오류: {e}")
            return False

def main():
    """명령줄 인터페이스"""
    parser = argparse.ArgumentParser(description='Mini WeasyPrint - 경량 HTML to PDF 변환기')
    parser.add_argument('input', help='입력 HTML 파일')
    parser.add_argument('output', help='출력 PDF 파일')
    parser.add_argument('--page-size', choices=['A4', 'letter'], default='A4',
                       help='페이지 크기 (기본값: A4)')
    
    args = parser.parse_args()
    
    # 페이지 크기 설정
    page_size = A4 if args.page_size == 'A4' else letter
    
    # 변환 실행
    converter = MiniWeasyPrint()
    converter.page_size = page_size
    
    success = converter.html_file_to_pdf(args.input, args.output)
    
    if success:
        print("변환 완료!")
        sys.exit(0)
    else:
        print("변환 실패!")
        sys.exit(1)

# 사용 예제
def example_usage():
    """사용 예제"""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            h1 { color: blue; text-align: center; }
            p { color: black; font-size: 14pt; }
            .highlight { background-color: yellow; }
        </style>
    </head>
    <body>
        <h1>Mini WeasyPrint 테스트</h1>
        <h2>소제목</h2>
        <p>이것은 <strong>굵은 텍스트</strong>와 <em>기울임 텍스트</em>가 있는 단락입니다.</p>
        <p class="highlight">이 단락은 하이라이트됩니다.</p>
        <hr>
        <h3>목록 예제</h3>
        <p>• 첫 번째 항목</p>
        <p>• 두 번째 항목</p>
        <p>• 세 번째 항목</p>
    </body>
    </html>
    """
    
    converter = MiniWeasyPrint()
    converter.html_to_pdf(html_content, 'example_output.pdf')

if __name__ == '__main__':
    if len(sys.argv) == 1:
        # 인자가 없으면 예제 실행
        print("Mini WeasyPrint 예제 실행 중...")
        example_usage()
    else:
        # 명령줄 모드
        main()