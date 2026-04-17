# Windows-style executable help — LLM rules

You are generating a Windows-style console executable (C#, C++, or
similar) and want its `/?` output to be auto-importable by ScripTree.
Follow these rules.

## Hard rules

1. **Respond to `/?`, `-h`, and `--help` with the same text.** ScripTree
   probes all four. Producing help for only one is fine but supporting
   all four maximizes compatibility with other tools too.
2. **Write help to stdout, not stderr, not MessageBox.** The probe
   captures stdout first.
3. **Exit 0 after printing help.** Non-zero exits under 50 chars of
   output cause the probe to discard the output and try the next probe
   argument.
4. **Start with a one-line summary, then a blank line, then
   `Usage:`.** This is the canonical entry point for the heuristic
   parser.
5. **One flag per line, indented by exactly 2 spaces.**
6. **Separate flag and description with ≥2 spaces or a tab.**
7. **Use `/FLAG` for booleans and `/FLAG:value` or `/FLAG value` for
   string-valued options.** Do not invent other syntaxes.
8. **Describe path arguments with "file", "folder", or "directory" in
   the description.** ScripTree promotes these to native file pickers.

## Template

```
MYTOOL - One sentence describing what this tool does.

Usage: mytool.exe [/V] [/N count] [/MODE:mode] [/OUT file] <input> [output]

  <input>         Path to the input file to process.
  [output]        Optional output file (defaults to stdout).
  /V              Enable verbose diagnostic output.
  /N count        Number of iterations to run. Default: 10.
  /MODE:mode      Processing mode: fast, slow, or auto.
  /OUT file       Write results to the given file instead of stdout.
  /?              Show this help and exit.

Examples:
  mytool.exe C:\input.txt
  mytool.exe /V /N 5 /MODE:fast C:\input.txt C:\output.txt
```

## C# reference implementation

```csharp
static int Main(string[] args)
{
    if (args.Length == 0 ||
        args.Contains("/?") || args.Contains("-h") ||
        args.Contains("--help"))
    {
        PrintHelp();
        return 0;
    }
    // ... actual argument parsing ...
}

static void PrintHelp()
{
    Console.WriteLine("MYTOOL - One sentence describing what this tool does.");
    Console.WriteLine();
    Console.WriteLine("Usage: mytool.exe [/V] [/N count] [/MODE:mode] [/OUT file] <input> [output]");
    Console.WriteLine();
    Console.WriteLine("  <input>         Path to the input file to process.");
    Console.WriteLine("  [output]        Optional output file (defaults to stdout).");
    Console.WriteLine("  /V              Enable verbose diagnostic output.");
    Console.WriteLine("  /N count        Number of iterations to run. Default: 10.");
    Console.WriteLine("  /MODE:mode      Processing mode: fast, slow, or auto.");
    Console.WriteLine("  /OUT file       Write results to the given file instead of stdout.");
    Console.WriteLine("  /?              Show this help and exit.");
    Console.WriteLine();
    Console.WriteLine("Examples:");
    Console.WriteLine("  mytool.exe C:\\input.txt");
    Console.WriteLine("  mytool.exe /V /N 5 /MODE:fast C:\\input.txt C:\\output.txt");
}
```

ScripTree's heuristic parser produces: `input` (file_open, required),
`output` (file_save, optional), `/V` checkbox, `/N` number spin box
(keyword "number" in description), `/MODE` dropdown with three
choices (extracted from the description), `/OUT` file_save picker.

## Alternative: System.CommandLine (preferred for new code)

If you're writing new C# code, use `System.CommandLine`. Its
auto-generated help is argparse-shaped and ScripTree's argparse
detector catches it:

```csharp
var root = new RootCommand("One sentence describing what this tool does.");
var input = new Argument<FileInfo>("input", "Path to the input file");
var verbose = new Option<bool>(["/V", "--verbose"], "Print diagnostic output");
var count = new Option<int>(["/N", "--count"], getDefaultValue: () => 10,
    description: "Number of iterations to run");
root.AddArgument(input);
root.AddOption(verbose);
root.AddOption(count);
return root.Invoke(args);
```

The help output this generates is parsed by the argparse detector with
high confidence. Recommended for any new Windows CLI tool.

## Do not

- **Do not** use `MessageBox.Show` for help, even for GUI apps with a
  CLI mode.
- **Do not** mix `/flag` and `--flag` syntax in the same tool's help
  (pick one).
- **Do not** print a box-drawing ASCII banner above the usage line.
  The heuristic parser keys on column positions and banners break it.
- **Do not** put descriptions on separate lines from the flag:
  ```
    /V
      Enable verbose output.
  ```
  This parses as two separate "flags", neither of which is valid.
  Use:
  ```
    /V            Enable verbose output.
  ```
- **Do not** emit help through a pager. The probe runs headless and
  isn't a terminal.

## Verifying before shipping

```
mytool.exe /? > help.txt
```

Then import into ScripTree and confirm the produced draft has the
right param count, types, and widgets. Iterate on the help text, not
on the `.scriptree` file — the `.scriptree` is regenerated any time
the tool is re-parsed.
