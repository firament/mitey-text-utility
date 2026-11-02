# mitey Text Utility

mitey Text Utility version 1.0.2 is a text editor and a text viewer in one HTML file. You open `mitey-text-utility.html` in a browser. You edit text in the left pane. The right pane shows the rendered text. The page stores your text in the browser.

## Design approach

The product is one HTML file. That file holds the page layout, the style rules, and the script. You do not install an application framework to run it.

When the browser can reach the network, the page loads its libraries from public hosts. When you need a copy that works with no network, you run `make-mtu-offline.py`. That script copies `mitey-text-utility.html` into `dist`, then downloads the libraries into an offline file.

The script saves the editor text, the file name, and the settings in local storage (data kept by the browser on this computer). A version change replaces the saved help text with the help text for the new version. The first visit, or empty saved text, loads the built-in help text.

The editor and the viewer sit side by side. You drag a splitter to set the width of each pane. A table of contents sits beside the viewer, and a second splitter sets its width. The page remembers both widths.

Print uses the browser print dialog. A table in the viewer repeats a header and a footer on each printed page. Those lines come from front matter (a short block of name and value pairs between `---` marks at the top of the file). Exported HTML stays light. The toolbar follows the color scheme of the operating system. The viewer stays light until you set `PREVIEW_THEME` to `dark` in the HTML file and reload the page.

## Features

The toolbar groups commands in the File, Edit, View, Export, and Settings menus. Wrap, line numbers, and the table of contents also appear as buttons on the toolbar. If you want those buttons hidden, set `USE_SETTINGS_DROPDOWN` to `true` in the HTML file. Reload the page.

File, edit, and view:

- Open a file from disk, or drop a file on the page.
- Save the editor text as a UTF-8 file.
- Refresh the viewer, restore the help text, or reset the saved settings.
- Select all text, go to a line, copy text, paste text, or trim spaces at the end of each line.
- Show the editor and the viewer together, show only the editor, or show only the viewer.

Export and print:

- Print or save a PDF from the browser print dialog.
- Copy or save the viewer as an HTML fragment or as a full HTML page. A saved page puts a table of contents on the right when the document has headings. A button at the top right shows or hides it, and you drag its edge to set the width. The document and the table of contents scroll separately. The heading in view stays marked. The page script and the Markdown and code styles are inside the file.
- Name the export file from the front matter title, the opened file name, or the first heading.

Viewer and text:

- Render GitHub Flavored Markdown with tables, task lists, strikethrough, and alerts (Note, Tip, Important, Warning, Caution).
- Turn a single newline in a paragraph into a line break when Line Breaks is on.
- Show or hide the table of contents.
- Track the heading that is in view.
- Show front matter as a table when Front Matter is on. Each key in that table starts with a capital letter.
- Keep front matter hidden from the viewer by default.
- Color code blocks and other text files with highlight.js. A code fence with no language is plain text.
- Force plain text for every file when Plain Text All is on.
- Allow or block images that load from http or https.
- Show a notice for copy, save, file type, a blocked image, or a settings reset.
- Rename the loaded file from the status label.

Enter saves the new file name. Esc cancels the rename. The browser tab title uses the opened file name, the front matter title, or the first heading.

| Shortcut | Action |
|----------|--------|
| Ctrl+O | Open a file |
| Ctrl+R | Refresh the viewer |
| Ctrl+P | Export a PDF |
| Ctrl+F | Find text in the editor |
| Ctrl+G | Go to a line in the editor |
| Tab | Insert four spaces in the editor |

## Technologies

The online page loads these libraries from public hosts:

- CodeMirror 5.65.20 is the text editor.
- marked renders Markdown.
- github-markdown-css 5.9.0 styles the viewer.
- highlight.js 11.11.1 colors source code, and PowerShell is loaded as an extra language.

The page script is plain JavaScript. It uses the browser for local storage, for opening a file, for saving a file, and for print. Body text uses Carlito, then Calibri. Headings use Caladea, then Cambria. Code uses Fira Code, then Consolas.

`make-mtu-offline.py` uses only the Python 3.8 standard library. It does not add a package list. The script copies `mitey-text-utility.html` to a versioned file in `dist`, then bundles that copy.

## Build a dist copy

You need Python 3.8 or later on the computer. You need a network connection while the command runs. The first argument is the version number, for example `1.0.0`. The command starts in the folder that holds `mitey-text-utility.html`.

1. Open a terminal in the folder that holds `mitey-text-utility.html`.
2. Run `python make-mtu-offline.py 1.0.2`.
3. Open `dist/mitey-text-utility-102.html` when the network is available.
4. If you have no network, open `dist/mitey-text-utility-102-offline.html` in the browser.

The version `1.0.2` drops the dots and becomes `102` in both file names. The script copies the source to `dist/mitey-text-utility-102.html`. It then reads that copy and writes `dist/mitey-text-utility-102-offline.html`. Pass `--input` or `--output` only when you want a different file name.
