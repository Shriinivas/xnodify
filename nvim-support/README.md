# XFY Neovim Support

LSP server and Neovim integration for `.xfy` (XNodify) script files.

## Status: ✅ COMPLETE

All planned phases implemented!

| Phase | Feature | Status |
|-------|---------|--------|
| Phase 1 | Diagnostics | ✅ Complete |
| Phase 2 | Go-to-definition, includes | ✅ Complete |
| Phase 3 | Autocomplete | ✅ Complete |
| Phase 4 | Signature Help | ✅ Complete |
| Phase 5 | Syntax highlighting | ✅ Complete (vim syntax) |
| Bonus | Hover documentation | ✅ Complete |

## Features

### LSP Server
- **Diagnostics**: Real-time syntax errors, undefined variables, unused inputs
- **Autocomplete**: 382 nodes, 79 shortcuts, keywords, types
- **Go to Definition**: Jump to group definitions, included files
- **Signature Help**: Parameter hints with types while typing
- **Hover**: Documentation for nodes, shortcuts, keywords, types

### Nvim Integration
- **Filetype Detection**: `.xfy` files recognized
- **Commenting**: `gcc` toggles `#` comments
- **Syntax Highlighting**: Full XFY syntax + embedded Python in ``` blocks

## Architecture

**Single Source of Truth Principle:**
```
LSP Server imports directly from xnodify root:
├── parser.py          → Parsing and preprocessing
├── semantic_analyzer.py → Validation without Blender
├── registry.py        → 382 node definitions
├── shortcuts.py       → 79 shortcut mappings
└── validation.py      → Shared validation rules
```

No code duplication - changes to parser/compiler automatically reflected in LSP.

## Prerequisites

```bash
pip install pygls lsprotocol
```

## Setup Instructions

### Option 1: Use existing nvim config (Recommended)

The LSP config and syntax files are already in `~/.config/nvim/`:
- `ftdetect/xfy.lua` - Filetype detection
- `after/ftplugin/xfy.lua` - Comment settings
- `syntax/xfy.vim` - Syntax highlighting

Just ensure your LSP config includes xfy-lsp (see below).

### Option 2: Add to runtimepath

Add to your Neovim config:
```lua
vim.opt.runtimepath:append("/path/to/xnodify/nvim-support/nvim")
```

### LSP Client Config

Add to your nvim LSP configuration:
```lua
local lspconfig = require('lspconfig')
local configs = require('lspconfig.configs')

if not configs.xfy_lsp then
  configs.xfy_lsp = {
    default_config = {
      cmd = { 'python3', '/path/to/xnodify/nvim-support/xfy-lsp/server.py' },
      filetypes = { 'xfy' },
      root_dir = function(fname)
        return lspconfig.util.find_git_ancestor(fname) or vim.fn.getcwd()
      end,
    },
  }
end

lspconfig.xfy_lsp.setup{}
```

## Usage

| Action | Trigger | Description |
|--------|---------|-------------|
| Autocomplete | `Ctrl+Space` or typing | Show completions |
| Go to Definition | `gd` | Jump to group/include |
| Signature Help | `(` or `,` | Show parameters |
| Hover | `K` | Show documentation |
| Comment | `gcc` | Toggle `#` comment |
| Diagnostics | Auto | Errors shown inline |

## Testing

### Verify LSP is Running
```vim
:LspInfo
```
Should show `xfy_lsp` attached.

### Test Autocomplete
Type `inp` → should show `input` keyword and `input_*` nodes.

### Test Go to Definition
Place cursor on a group name, press `gd` → jumps to definition.

### Test Hover
Place cursor on `mesh_cube`, press `K` → shows node documentation.

## Troubleshooting

### LSP Not Starting
```bash
# Check pygls installed
python3 -c "from pygls.server import LanguageServer; print('OK')"

# Check server runs
python3 /path/to/server.py --help
```

### Check Logs
```vim
:LspLog
```

### Filetype Not Detected
```vim
:set filetype?
```
Should show `filetype=xfy`. If not, check ftdetect is loaded.

## Directory Structure

```
nvim-support/
├── xfy-lsp/
│   └── server.py          # LSP server (pygls)
├── nvim/
│   ├── ftdetect/xfy.lua   # Filetype detection
│   └── ftplugin/xfy.lua   # LSP client config
├── PHASE_1.5_TODO.md      # Implementation details
├── README.md              # This file
└── test_*.xfy             # Test files
```

## Development

### Modifying the Server
1. Edit `xfy-lsp/server.py`
2. In nvim: `:LspRestart`
3. Changes take effect immediately

### Adding Features
Server uses pygls framework. Add handlers for new LSP methods:
```python
@server.feature(TEXT_DOCUMENT_SOME_FEATURE)
def handler(ls, params):
    ...
```

## See Also

- `../XFY_AI_REFERENCE.md` - Complete language reference and syntax specification
- `../README.md` - Addon overview and installation guide
