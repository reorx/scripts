#!/usr/bin/env python3
"""
Unit tests for mdformat.py

Tests all the formatting rules:
- Remove duplicate empty lines
- Remove trailing whitespace
- No empty lines between list items
- Sublists indented by 4 spaces
- One empty line after block elements
"""

import unittest
import tempfile
import os
from pathlib import Path
import sys

# Import the module we're testing
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mdformat


class TestMarkdownFormatter(unittest.TestCase):
    def test_remove_duplicate_empty_lines(self):
        """Test removal of consecutive empty lines."""
        input_content = 'Line 1\n\n\n\nLine 2\n\n\n\n\nLine 3'
        expected = 'Line 1\n\nLine 2\n\nLine 3'
        result = mdformat.remove_duplicate_empty_lines(input_content)
        self.assertEqual(result, expected)

    def test_remove_trailing_whitespace(self):
        """Test removal of trailing whitespace from lines."""
        input_content = 'Line 1   \nLine 2\t\t\n   Line 3   \n'
        expected = 'Line 1\nLine 2\n   Line 3\n'
        result = mdformat.remove_trailing_whitespace(input_content)
        self.assertEqual(result, expected)

    def test_is_list_item(self):
        """Test detection of list items."""
        # Unordered lists
        self.assertTrue(mdformat.is_list_item('- Item 1'))
        self.assertTrue(mdformat.is_list_item('* Item 2'))
        self.assertTrue(mdformat.is_list_item('+ Item 3'))
        self.assertTrue(mdformat.is_list_item('  - Indented item'))

        # Ordered lists
        self.assertTrue(mdformat.is_list_item('1. Item 1'))
        self.assertTrue(mdformat.is_list_item('12) Item 2'))
        self.assertTrue(mdformat.is_list_item('  3. Indented item'))

        # Non-list items
        self.assertFalse(mdformat.is_list_item('Regular paragraph'))
        self.assertFalse(mdformat.is_list_item('# Heading'))
        self.assertFalse(mdformat.is_list_item('> Blockquote'))
        self.assertFalse(mdformat.is_list_item(''))

    def test_get_list_indentation(self):
        """Test getting indentation level of list items."""
        self.assertEqual(mdformat.get_list_indentation('- Item'), 0)
        self.assertEqual(mdformat.get_list_indentation('  - Item'), 2)
        self.assertEqual(mdformat.get_list_indentation('    * Item'), 4)
        self.assertEqual(mdformat.get_list_indentation('        1. Item'), 8)

    def test_format_lists_remove_empty_lines(self):
        """Test removal of empty lines between list items."""
        input_content = """- Item 1

- Item 2


- Item 3"""
        expected = """- Item 1
- Item 2
- Item 3"""
        result = mdformat.format_lists(input_content)
        self.assertEqual(result, expected)

    def test_format_lists_sublist_indentation(self):
        """Test proper indentation of sublists (4 spaces)."""
        input_content = """- Item 1
  - Subitem 1
      - Sub-subitem 1
- Item 2"""
        expected = """- Item 1
    - Subitem 1
        - Sub-subitem 1
- Item 2"""
        result = mdformat.format_lists(input_content)
        self.assertEqual(result, expected)

    def test_format_lists_mixed_indentation(self):
        """Test fixing various incorrect indentations."""
        input_content = """- Item 1
      - Wrong indent (6 spaces)
        - Another wrong indent (8 spaces)
- Item 2
  - Correct indent (2 spaces) -> should become 4
    - Should become 8 spaces"""
        expected = """- Item 1
    - Wrong indent (6 spaces)
        - Another wrong indent (8 spaces)
- Item 2
    - Correct indent (2 spaces) -> should become 4
    - Should become 8 spaces"""
        result = mdformat.format_lists(input_content)
        self.assertEqual(result, expected)

    def test_format_lists_ordered(self):
        """Test formatting of ordered lists."""
        input_content = """1. First item

2. Second item

  3. Wrong indent"""
        expected = """1. First item
2. Second item
    3. Wrong indent"""
        result = mdformat.format_lists(input_content)
        self.assertEqual(result, expected)

    def test_ensure_block_spacing_headings(self):
        """Test proper spacing after headings."""
        input_content = """# Heading 1
Paragraph after heading.

## Heading 2


Paragraph with too many empty lines above."""
        expected = """# Heading 1

Paragraph after heading.

## Heading 2

Paragraph with too many empty lines above."""
        result = mdformat.ensure_block_spacing(input_content)
        self.assertEqual(result, expected)

    def test_ensure_block_spacing_blockquotes(self):
        """Test proper spacing after blockquotes."""
        input_content = """> This is a blockquote
> With multiple lines
Paragraph immediately after.

> Another quote


Paragraph with too many empty lines."""
        expected = """> This is a blockquote
> With multiple lines

Paragraph immediately after.

> Another quote

Paragraph with too many empty lines."""
        result = mdformat.ensure_block_spacing(input_content)
        self.assertEqual(result, expected)

    def test_ensure_block_spacing_lists(self):
        """Test proper spacing after lists."""
        input_content = """- List item 1
- List item 2
Paragraph immediately after.

1. Ordered item 1
2. Ordered item 2


Paragraph with too many empty lines."""
        expected = """- List item 1
- List item 2

Paragraph immediately after.

1. Ordered item 1
2. Ordered item 2

Paragraph with too many empty lines."""
        result = mdformat.ensure_block_spacing(input_content)
        self.assertEqual(result, expected)

    def test_is_end_of_block(self):
        """Test detection of block element endings."""
        lines = [
            '# Heading',
            'Paragraph text',
            '',
            '> Blockquote',
            '> More quote',
            'After quote',
            '- List item',
            '  Continuation',
            'After list',
        ]

        # Heading should be end of block
        self.assertTrue(mdformat.is_end_of_block(lines[0], lines, 0))

        # Paragraph before empty line should be end of block
        self.assertTrue(mdformat.is_end_of_block(lines[1], lines, 1))

        # Last line of blockquote should be end of block
        self.assertTrue(mdformat.is_end_of_block(lines[4], lines, 4))

        # List item with continuation should not be end of block
        self.assertFalse(mdformat.is_end_of_block(lines[6], lines, 6))

    def test_complex_document_formatting(self):
        """Test formatting a complex document with all rules applied."""
        input_content = """# Main Heading   


This is a paragraph with trailing spaces.   

## Subheading
Another paragraph.
- List item 1

- List item 2   

  - Subitem with wrong indentation


  - Another subitem


1. Ordered list item   

2. Another ordered item


> This is a blockquote   
> With multiple lines   
Some text after blockquote.

### Another heading


Final paragraph.   """

        expected = """# Main Heading

This is a paragraph with trailing spaces.

## Subheading

Another paragraph.

- List item 1
- List item 2
    - Subitem with wrong indentation
    - Another subitem

1. Ordered list item
2. Another ordered item

> This is a blockquote
> With multiple lines

Some text after blockquote.

### Another heading

Final paragraph.
"""

        result = mdformat.format_markdown(input_content)
        self.assertEqual(result, expected)

    def test_nested_lists_complex(self):
        """Test complex nested list scenarios."""
        input_content = """- Top level 1
  - Wrong indent sub 1
    - Wrong indent sub-sub 1
      - Wrong indent sub-sub-sub 1

- Top level 2

  - Another wrong indent
    Some continuation text


    - Deep nested item"""

        expected = """- Top level 1
    - Wrong indent sub 1
    - Wrong indent sub-sub 1
        - Wrong indent sub-sub-sub 1
- Top level 2
    - Another wrong indent
    Some continuation text
    - Deep nested item"""

        result = mdformat.format_lists(input_content)
        self.assertEqual(result, expected)

    def test_mixed_list_types(self):
        """Test mixing ordered and unordered lists."""
        input_content = """1. First ordered

   - Nested unordered

2. Second ordered

   1. Nested ordered

   2. Another nested ordered"""

        expected = """1. First ordered
    - Nested unordered
2. Second ordered
    1. Nested ordered
    2. Another nested ordered"""

        result = mdformat.format_lists(input_content)
        self.assertEqual(result, expected)

    def test_mixed_ordered_unordered_with_spacing(self):
        """Test ordered list with nested unordered items and empty lines."""
        input_content = """1. foo

   - foo 0
   - foo 1

2. bar

   - bar 0"""

        expected = """1. foo
    - foo 0
    - foo 1
2. bar
    - bar 0"""

        result = mdformat.format_lists(input_content)
        self.assertEqual(result, expected)

    def test_edge_case_empty_document(self):
        """Test handling of empty document."""
        result = mdformat.format_markdown('')
        self.assertEqual(result, '\n')

    def test_edge_case_only_whitespace(self):
        """Test handling of document with only whitespace."""
        input_content = '   \n\n\t\t\n   '
        expected = '\n'
        result = mdformat.format_markdown(input_content)
        self.assertEqual(result, expected)

    def test_edge_case_single_list_item(self):
        """Test handling of single list item."""
        input_content = '- Single item'
        expected = '- Single item\n'
        result = mdformat.format_markdown(input_content)
        self.assertEqual(result, expected)

    def test_preserve_code_blocks(self):
        """Test that code blocks are preserved correctly."""
        input_content = """Some text

```python
def hello():
    print("world")
```

More text"""

        # Code blocks should not be altered by list formatting
        result = mdformat.format_markdown(input_content)
        self.assertIn('```python', result)
        self.assertIn('def hello():', result)
        self.assertIn('print("world")', result)
        self.assertIn('```', result)

    def test_file_operations(self):
        """Test reading from file and writing to file."""
        test_content = """# Test File

- Item 1

- Item 2"""

        expected_content = """# Test File

- Item 1
- Item 2
"""

        # Create temporary input file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as input_file:
            input_file.write(test_content)
            input_file_path = input_file.name

        # Create temporary output file
        with tempfile.NamedTemporaryFile(suffix='.md', delete=False) as output_file:
            output_file_path = output_file.name

        try:
            # Test the main function by simulating command line args
            import sys

            original_argv = sys.argv
            sys.argv = ['mdformat.py', input_file_path, output_file_path]

            # Capture stdout to suppress output
            from io import StringIO

            original_stdout = sys.stdout
            sys.stdout = StringIO()

            try:
                mdformat.main()
            finally:
                sys.stdout = original_stdout
                sys.argv = original_argv

            # Read the output file and verify
            with open(output_file_path, 'r') as f:
                result = f.read()

            self.assertEqual(result, expected_content)

        finally:
            # Clean up temp files
            os.unlink(input_file_path)
            os.unlink(output_file_path)


class TestTexts(unittest.TestCase):
    def test_list_with_spaces(self):
        input_content = """1. **重中之重：补液！补液！补液！**
    
    - **首选“口服补液盐III”**：药店有售。这是世界卫生组织推荐的用于治疗腹泻脱水的首选药物，能完美补充水分和电解质，效果远优于清水、米汤或奶粉。请严格按照说明书用量冲泡。
        
    - **喂养方法**：遵循 **“少量多次”** 的原则。比如每5-10分钟喂5-10毫升（一两勺），用勺子、滴管或奶瓶都可以。这样既能保证水分摄入，又不会因为一次性喝得太多而刺激肠道，引起再次呕吐或加重腹泻。
        
2. **饮食调整（非常重要）**：
    
    - **暂停普通配方奶粉**：普通奶粉中的乳糖在此时可能难以消化，会加重腹泻。如果宝宝奶瘾重，建议购买 **“腹泻奶粉”（无乳糖配方奶粉）** 临时过渡，直到腹泻完全停止后3天再转回普通奶粉。
        
    - **辅食“做减法”**：
        
        - **立即停止**：像**炒南瓜丝**这样油腻、粗纤维、难消化的食物。
            
        - **推荐饮食**：只吃**清淡、温热、烂熟、无渣**的食物。
            
        - **首选**：**白米粥、小米油（粥上面那层糊）、烂面条**（不加油和调料）、**蒸苹果泥**（苹果蒸熟后捣成泥，其中的果胶有收敛止泻作用）。
            
        - **原则**：由少到多，由稀到稠。比如先喝米汤，没问题再吃少量米粥。

3. **臀部护理**：

    - 水样便对宝宝娇嫩皮肤的刺激很大，极易引起“红屁股”。
"""

        expected = """1. **重中之重：补液！补液！补液！**
    - **首选“口服补液盐III”**：药店有售。这是世界卫生组织推荐的用于治疗腹泻脱水的首选药物，能完美补充水分和电解质，效果远优于清水、米汤或奶粉。请严格按照说明书用量冲泡。
    - **喂养方法**：遵循 **“少量多次”** 的原则。比如每5-10分钟喂5-10毫升（一两勺），用勺子、滴管或奶瓶都可以。这样既能保证水分摄入，又不会因为一次性喝得太多而刺激肠道，引起再次呕吐或加重腹泻。
2. **饮食调整（非常重要）**：
    - **暂停普通配方奶粉**：普通奶粉中的乳糖在此时可能难以消化，会加重腹泻。如果宝宝奶瘾重，建议购买 **“腹泻奶粉”（无乳糖配方奶粉）** 临时过渡，直到腹泻完全停止后3天再转回普通奶粉。
    - **辅食“做减法”**：
        - **立即停止**：像**炒南瓜丝**这样油腻、粗纤维、难消化的食物。
        - **推荐饮食**：只吃**清淡、温热、烂熟、无渣**的食物。
        - **首选**：**白米粥、小米油（粥上面那层糊）、烂面条**（不加油和调料）、**蒸苹果泥**（苹果蒸熟后捣成泥，其中的果胶有收敛止泻作用）。
        - **原则**：由少到多，由稀到稠。比如先喝米汤，没问题再吃少量米粥。
3. **臀部护理**：
    - 水样便对宝宝娇嫩皮肤的刺激很大，极易引起“红屁股”。
"""

        result = mdformat.format_markdown(input_content)
        self.assertEqual(result, expected)


if __name__ == '__main__':
    unittest.main()
