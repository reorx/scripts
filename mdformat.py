#!/usr/bin/env python3
"""
Markdown formatter with custom rules.

This script formats Markdown files according to these rules:
- Remove duplicate empty lines (consecutive empty lines should not be more than one)
- Remove trailing whitespaces
- In ordered or bullet list, no empty lines between list items
- In ordered or bullet list, a sublist must be indented in 4 spaces
- There must be one empty line after a heading, a paragraph, a list, a blockquote...any block level element

Usage:
    python mdformat.py input.md [output.md]
    cat input.md | python mdformat.py
    cat input.md | python mdformat.py > output.md
    cat input.md | python mdformat.py - output.md

If no input file is specified or input is '-', reads from stdin.
If output.md is not specified, the formatted content will be printed to stdout.
"""

import sys
import re
import argparse
from pathlib import Path


def remove_duplicate_empty_lines(content: str) -> str:
    """Remove consecutive empty lines, allowing only single empty lines."""
    # Replace multiple consecutive empty lines with single empty line
    return re.sub(r'\n\s*\n\s*\n+', '\n\n', content)


def remove_trailing_whitespace(content: str) -> str:
    """Remove trailing whitespace from each line."""
    lines = content.split('\n')
    return '\n'.join(line.rstrip() for line in lines)


def format_lists(content: str) -> str:
    """
    Format lists to ensure:
    1. No empty lines between list items at the same level
    2. Sublists are indented by 4 spaces from their parent
    """
    lines = content.split('\n')
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Check if current line is a list item
        if is_list_item(line):
            # Process the entire list hierarchy starting from this point
            list_block, consumed = process_list_hierarchy(lines, i)
            result.extend(list_block)
            i += consumed
        else:
            result.append(line)
            i += 1

    return '\n'.join(result)


def is_list_item(line: str) -> bool:
    """Check if a line is a list item (ordered or unordered)."""
    stripped = line.lstrip()
    # Unordered list markers: -, *, +
    if re.match(r'^[-*+]\s+', stripped):
        return True
    # Ordered list markers: number followed by . or )
    if re.match(r'^\d+[.)]\s+', stripped):
        return True
    return False


def get_list_indentation(line: str) -> int:
    """Get the indentation level of a list item."""
    return len(line) - len(line.lstrip())


def process_list_hierarchy(lines: list, start_idx: int) -> tuple:
    """
    Process a complete list hierarchy, fixing indentation and removing empty lines between items.
    Returns (processed_lines, lines_consumed)
    """
    result = []
    i = start_idx

    if i >= len(lines) or not is_list_item(lines[i]):
        return result, 0

    base_indent = get_list_indentation(lines[i])
    indent_levels = [base_indent]  # Track all indentation levels seen

    while i < len(lines):
        line = lines[i]

        # Empty line - check if we should keep it
        if not line.strip():
            # Look ahead to see what comes next
            next_non_empty_idx = find_next_non_empty_line(lines, i + 1)

            if next_non_empty_idx == -1:
                # End of document
                result.append(line)
                i += 1
                break

            next_line = lines[next_non_empty_idx]

            # If next line is still part of the list hierarchy, skip this empty line
            if is_list_item(next_line) and get_list_indentation(next_line) >= base_indent:
                i += 1
                continue
            elif next_line.startswith(' ') and get_list_indentation(next_line) > base_indent:
                # Continuation content
                i += 1
                continue
            else:
                # Next line is not part of the list, keep the empty line and break
                result.append(line)
                i += 1
                break

        # Non-empty line
        if is_list_item(line):
            current_indent = get_list_indentation(line)

            if current_indent < base_indent:
                # This list item is at a higher level, stop processing
                break
            elif current_indent == base_indent:
                # Same level as base
                result.append(line)
                i += 1
            else:
                # This is a nested list item - find the correct parent level
                parent_level = base_indent
                for level in sorted(indent_levels, reverse=True):
                    if level < current_indent:
                        parent_level = level
                        break

                # Calculate proper indentation (4 spaces from parent)
                proper_indent = parent_level + 4

                # Add this level to our tracking if it's new
                if proper_indent not in indent_levels:
                    indent_levels.append(proper_indent)

                # Create corrected line
                line_content = line.lstrip()
                corrected_line = ' ' * proper_indent + line_content
                result.append(corrected_line)
                i += 1
        elif line.startswith(' ') and get_list_indentation(line) > base_indent:
            # Continuation of list item (indented content) - keep as is
            result.append(line)
            i += 1
        else:
            # Not part of the list anymore
            break

    return result, i - start_idx


def find_next_non_empty_line(lines: list, start_idx: int) -> int:
    """Find the index of the next non-empty line."""
    for i in range(start_idx, len(lines)):
        if lines[i].strip():
            return i
    return -1


def ensure_block_spacing(content: str) -> str:
    """
    Ensure there's exactly one empty line after block-level elements
    (headings, paragraphs, lists, blockquotes).
    """
    lines = content.split('\n')
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]
        result.append(line)

        # Check if current line is end of a block element
        if is_end_of_block(line, lines, i):
            # Look ahead to see if there's already proper spacing
            next_non_empty_idx = find_next_non_empty_line(lines, i + 1)

            if next_non_empty_idx != -1:  # There's more content after this
                empty_lines_between = next_non_empty_idx - i - 1

                if empty_lines_between == 0:
                    # No empty line, add one
                    result.append('')
                elif empty_lines_between > 1:
                    # Too many empty lines, add just one
                    result.append('')
                    # Skip the extra empty lines
                    i = next_non_empty_idx - 1
                else:
                    # Exactly one empty line, keep it as is
                    pass

        i += 1

    return '\n'.join(result)


def is_end_of_block(line: str, lines: list, idx: int) -> bool:
    """Check if the current line is the end of a block-level element."""
    if not line.strip():
        return False

    # Headings (ATX style)
    if line.lstrip().startswith('#'):
        return True

    # Blockquote end (line starts with > but next doesn't or is empty)
    if line.lstrip().startswith('>'):
        next_idx = idx + 1
        if next_idx >= len(lines):
            return True
        next_line = lines[next_idx]
        if not next_line.strip() or not next_line.lstrip().startswith('>'):
            return True

    # List end - check if this is the last item in a list
    if is_list_item(line):
        next_non_empty_idx = find_next_non_empty_line(lines, idx + 1)
        if next_non_empty_idx == -1:  # End of document
            return True
        next_line = lines[next_non_empty_idx]

        current_indent = get_list_indentation(line)
        next_indent = get_list_indentation(next_line)

        # If next line is not a list item or continuation, this is end of list
        if not is_list_item(next_line) and next_indent <= current_indent:
            return True
        # If next line is a list item but at a lower level, check if it continues a parent list
        if is_list_item(next_line) and next_indent < current_indent:
            # Check if the next line is the same type of list (ordered/unordered)
            next_is_ordered = re.match(r'^\s*\d+[.)]\s+', next_line)

            # Look backwards to see if there's a parent list at the same level as next_line
            for back_idx in range(idx - 1, -1, -1):
                back_line = lines[back_idx]
                if not back_line.strip():
                    continue
                if is_list_item(back_line):
                    back_indent = get_list_indentation(back_line)
                    # If we find a list item at the same level as next_line
                    if back_indent == next_indent:
                        # Check if it's the same type of list
                        back_is_ordered = re.match(r'^\s*\d+[.)]\s+', back_line)
                        # Only continue if both are ordered or both are unordered
                        if (next_is_ordered and back_is_ordered) or (not next_is_ordered and not back_is_ordered):
                            return False  # Don't add spacing, this is continuing the parent list
                        else:
                            return True  # Different list types, add spacing
                    # If we find a list item at higher level, stop looking
                    if back_indent < current_indent:
                        break
                else:
                    # Non-list item, stop looking backwards
                    break
            return True

        # Check if this is the end of one list type and start of another at same level
        if is_list_item(next_line) and next_indent == current_indent:
            # Check if they're different list types
            current_is_ordered = re.match(r'^\s*\d+[.)]\s+', line)
            next_is_ordered = re.match(r'^\s*\d+[.)]\s+', next_line)

            if (current_is_ordered and not next_is_ordered) or (not current_is_ordered and next_is_ordered):
                return True  # Different list types at same level, add spacing

    # Paragraph end (current line has content, next is different block or empty)
    if (
        line.strip()
        and not line.lstrip().startswith('#')
        and not line.lstrip().startswith('>')
        and not is_list_item(line)
    ):
        next_idx = idx + 1
        if next_idx >= len(lines):
            return True

        # Look for next non-empty line
        next_non_empty_idx = find_next_non_empty_line(lines, next_idx)
        if next_non_empty_idx == -1:
            return True

        next_line = lines[next_non_empty_idx]
        # If next line starts a new block type, current line ends a paragraph
        if (
            next_line.lstrip().startswith('#')
            or next_line.lstrip().startswith('>')
            or is_list_item(next_line)
            or next_line.strip().startswith('```')
        ):
            return True

    return False


def format_markdown(content: str) -> str:
    """Apply all formatting rules to the markdown content."""
    # Step 1: Remove trailing whitespace
    content = remove_trailing_whitespace(content)

    # Step 2: Remove duplicate empty lines
    content = remove_duplicate_empty_lines(content)

    # Step 3: Format lists (remove empty lines between items, fix indentation)
    content = format_lists(content)

    # Step 4: Ensure proper block spacing
    content = ensure_block_spacing(content)

    # Step 5: Final cleanup - remove duplicate empty lines again
    content = remove_duplicate_empty_lines(content)

    # Step 6: Ensure document ends with exactly one newline
    content = content.rstrip() + '\n'

    return content


def main():
    """Main function to handle command-line usage."""
    parser = argparse.ArgumentParser(
        description='Format Markdown files according to custom rules',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split('Usage:')[1] if 'Usage:' in __doc__ else '',
    )
    parser.add_argument('input', nargs='?', help='Input Markdown file (optional, defaults to stdin)')
    parser.add_argument('output', nargs='?', help='Output file (optional, defaults to stdout)')

    args = parser.parse_args()

    # Read input
    try:
        if args.input and args.input != '-':
            # Read from file
            input_path = Path(args.input)
            content = input_path.read_text(encoding='utf-8')
        else:
            # Read from stdin (either no input specified or input is '-')
            content = sys.stdin.read()
    except Exception as e:
        print(f'Error reading input: {e}', file=sys.stderr)
        sys.exit(1)

    # Format the content
    formatted_content = format_markdown(content)

    # Write output
    if args.output:
        try:
            output_path = Path(args.output)
            output_path.write_text(formatted_content, encoding='utf-8')
            print(f'Formatted content written to {args.output}')
        except Exception as e:
            print(f'Error writing output file: {e}', file=sys.stderr)
            sys.exit(1)
    else:
        print(formatted_content, end='')


if __name__ == '__main__':
    main()
