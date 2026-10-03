"""
Source map for tracking line number transformations during preprocessing.

This module provides functionality to map preprocessed line numbers back to
their original source file locations, accounting for:
- Include expansions (inlining other files)
- Macro preprocessing (commenting out py!. lines)
"""


class SourceMap:
    """Maps preprocessed line numbers back to original source locations."""
    
    def __init__(self):
        # List of (preprocessed_line_start, preprocessed_line_end, original_file, original_line_start)
        # Represents that preprocessed lines [start, end) came from original_file starting at original_line_start
        self.mappings = []
    
    def add_range(self, preprocessed_start, preprocessed_end, original_file, original_start):
        """
        Record a range mapping.
        
        Args:
            preprocessed_start: Starting line in preprocessed text (1-indexed)
            preprocessed_end: Ending line in preprocessed text (1-indexed, exclusive)
            original_file: Path to original source file
            original_start: Starting line in original file (1-indexed)
        """
        self.mappings.append((preprocessed_start, preprocessed_end, original_file, original_start))
    
    def get_original_location(self, preprocessed_line):
        """
        Get original source location for a preprocessed line number.
        
        Args:
            preprocessed_line: Line number in preprocessed text (1-indexed)
            
        Returns:
            (filepath, line_number) tuple, or (None, preprocessed_line) if no mapping found
        """
        for prep_start, prep_end, orig_file, orig_start in self.mappings:
            if prep_start <= preprocessed_line < prep_end:
                # Calculate offset within this range
                offset = preprocessed_line - prep_start
                original_line = orig_start + offset
                return (orig_file, original_line)
        
        # No mapping found - return None for file and original line number
        return (None, preprocessed_line)
    
    def adjust_for_insertions(self, insertion_line, num_lines):
        """
        Adjust all mappings after an insertion point.
        
        When lines are inserted (e.g., commenting out lines), mappings after
        the insertion point need to be shifted.
        
        Args:
            insertion_line: Line where insertion occurred (1-indexed)
            num_lines: Number of lines inserted (can be negative for deletions)
        """
        adjusted_mappings = []
        for prep_start, prep_end, orig_file, orig_start in self.mappings:
            # If this mapping starts at or after insertion, shift it
            if prep_start >= insertion_line:
                new_start = prep_start + num_lines
                new_end = prep_end + num_lines
                adjusted_mappings.append((new_start, new_end, orig_file, orig_start))
            # If this mapping spans the insertion point, split it
            elif prep_start < insertion_line < prep_end:
                # Keep the part before insertion as-is
                adjusted_mappings.append((prep_start, insertion_line, orig_file, orig_start))
                # Shift the part after insertion
                offset_to_insertion = insertion_line - prep_start
                new_start = insertion_line + num_lines
                new_end = prep_end + num_lines
                new_orig_start = orig_start + offset_to_insertion
                adjusted_mappings.append((new_start, new_end, orig_file, new_orig_start))
            else:
                # This mapping is before insertion, keep as-is
                adjusted_mappings.append((prep_start, prep_end, orig_file, orig_start))
        
        self.mappings = adjusted_mappings
