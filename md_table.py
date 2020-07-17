import re
import sys
from bs4 import BeautifulSoup


th_td_regex = re.compile(r'th|td')


class ConvertError(Exception):
    pass


def html_table_to_markdown(html, align=False):
    soup = BeautifulSoup(html, 'html.parser')
    thead = soup.find('thead')
    tbody = soup.find('tbody')
    lines = []

    # thead > tr > th|td
    head_cells = None
    if thead:
        thead_tr = thead.find('tr')
        if thead_tr:
            head_cells = thead_tr.find_all(th_td_regex)

    # tbody > tr
    body_rows = None
    if tbody:
        body_rows = tbody.find_all('tr')

    if body_rows:
        row_num = 0
        for row in body_rows:
            cells = row.find_all(th_td_regex)
            if row_num == 0:
                if head_cells:
                    handle_head_cells(head_cells, lines)
                    handle_body_cells(cells, lines)
                else:
                    handle_head_cells(cells, lines)
            else:
                handle_body_cells(cells, lines)
            row_num += 1
    else:
        if not head_cells:
            raise ConvertError('neither thead nor tbody has content')
        handle_head_cells(head_cells, lines)

    for i in lines:
        print(i)


def handle_head_cells(els, lines):
    lines.append('| ' + ' | '.join(get_texts_from_els(els)) + ' |')
    lines.append('| ' + ' | '.join(len(text) * '-' for text in get_texts_from_els(els)) + ' |')


def handle_body_cells(els, lines):
    lines.append('| ' + ' | '.join(get_texts_from_els(els)) + ' |')


def get_texts_from_els(els):
    return [el.get_text().strip() for el in els]


def main():
    with open(sys.argv[1], 'r') as f:
        html = f.read()

    html_table_to_markdown(html)


if __name__ == '__main__':
    main()
