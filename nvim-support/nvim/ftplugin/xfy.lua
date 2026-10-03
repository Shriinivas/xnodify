-- XFY filetype plugin for Neovim
-- Auto-starts the XFY LSP server for .xfy files

local root_dir = vim.fn.getcwd()

-- Find the xfy-lsp server path
local script_path = debug.getinfo(1, "S").source:sub(2)
local nvim_support_dir = vim.fn.fnamemodify(script_path, ":h:h:h")
local lsp_server_path = nvim_support_dir .. "/xfy-lsp/server.py"

-- Check if server exists
if vim.fn.filereadable(lsp_server_path) == 0 then
  vim.notify("XFY LSP server not found at: " .. lsp_server_path, vim.log.levels.WARN)
  return
end

-- Configure the LSP client
local client = vim.lsp.start({
  name = "xfy-lsp",
  cmd = { "python3", lsp_server_path },
  root_dir = root_dir,
  filetypes = { "xfy" },
})

if client then
  vim.lsp.buf_attach_client(0, client)
end
