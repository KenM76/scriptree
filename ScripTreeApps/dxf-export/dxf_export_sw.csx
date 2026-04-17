// === DXF Export Script (SolidWorks stage) ===
// Reads the target assembly path, config name, output dir, and BOM template
// path from environment variables, opens the assembly, inserts a BOM,
// exports PLATE/SHEET rows as raw DXFs + tapped sidecars.
// Does NOT run cleanup or PDF — the Python wrapper handles those.

// --- Read parameters from environment ---
string assemblyPath = Environment.GetEnvironmentVariable("DXFEXPORT_ASSEMBLY") ?? "";
string configName = Environment.GetEnvironmentVariable("DXFEXPORT_CONFIG") ?? "";
string outputDir = Environment.GetEnvironmentVariable("DXFEXPORT_OUTPUT_DIR") ?? "";
string bomTemplate = Environment.GetEnvironmentVariable("DXFEXPORT_BOM_TEMPLATE") ?? "";

if (string.IsNullOrEmpty(assemblyPath)) { Console.WriteLine("ERROR: DXFEXPORT_ASSEMBLY env var not set"); return; }
if (string.IsNullOrEmpty(configName)) { Console.WriteLine("ERROR: DXFEXPORT_CONFIG env var not set"); return; }
if (string.IsNullOrEmpty(outputDir)) { Console.WriteLine("ERROR: DXFEXPORT_OUTPUT_DIR env var not set"); return; }
if (string.IsNullOrEmpty(bomTemplate)) { Console.WriteLine("ERROR: DXFEXPORT_BOM_TEMPLATE env var not set"); return; }

// Ensure output directory exists
try { System.IO.Directory.CreateDirectory(outputDir); } catch { }

// Use a local variable since swDoc is init-only
ModelDoc2 activeDoc = (ModelDoc2)swDoc;

// If the target assembly is not the active document, open it
if (activeDoc == null || activeDoc.GetType() != 2 || !string.Equals(activeDoc.GetPathName(), assemblyPath, StringComparison.OrdinalIgnoreCase))
{
    Console.WriteLine($"Opening assembly: {assemblyPath}");
    int oerrs = 0, owrns = 0;
    var opened = (ModelDoc2)swApp.OpenDoc6(assemblyPath, 2, 0, "", ref oerrs, ref owrns);
    if (opened == null)
        opened = (ModelDoc2)swApp.GetOpenDocumentByName(assemblyPath);
    if (opened == null) { Console.WriteLine($"ERROR: Could not open assembly (errs={oerrs} warns={owrns})"); return; }
    int ae0 = 0;
    swApp.ActivateDoc3(opened.GetTitle(), false, 0, ref ae0);
    activeDoc = opened;
}

if (activeDoc == null || activeDoc.GetType() != 2) { Console.WriteLine("ERROR: Active document is not an assembly"); return; }

string assyTitle = activeDoc.GetTitle();
Console.WriteLine($"Assembly: {assyTitle}");
Console.WriteLine($"Config: {configName}");
Console.WriteLine($"Output: {outputDir}");

// === PHASE 1: Insert BOM, read PLATE rows ===
var ext = (ModelDocExtension)activeDoc.Extension;
var bomAnnotObj = ext.InsertBomTable4(bomTemplate, 0, 0, 1, configName, false, 1, true, false);
if (bomAnnotObj == null) { Console.WriteLine("ERROR: BOM insertion failed"); return; }

var bomAnnot = (BomTableAnnotation)bomAnnotObj;
var bomFeat = (BomFeature)bomAnnot.BomFeature;
bomFeat.PartConfigurationGrouping = 1;
bomFeat.DisplayAsOneItem = true;
activeDoc.ForceRebuild3(false);

var tableAnnot = (TableAnnotation)bomAnnot;
int rowCount = tableAnnot.RowCount;
int colCount = tableAnnot.ColumnCount;
int headerCount = tableAnnot.GetHeaderCount();

// Find column indices
int partnoCol = -1, materialCol = -1, cutListCol = -1, configCol = -1, descCol = -1, qtyCol = -1;
for (int c = 0; c < colCount; c++)
{
    string t = (tableAnnot.GetColumnTitle2(c, false) ?? "").ToUpper();
    if (t == "PARTNO") partnoCol = c;
    else if (t == "MATERIAL") materialCol = c;
    else if (t == "DESCRIPTION") descCol = c;
    else if (t == "QTY") qtyCol = c;
    else if (t.Contains("CUT LIST ITEM NAME")) cutListCol = c;
    else if (t.Contains("CONFIGURATION NAME")) configCol = c;
}
Console.WriteLine($"Cols: PARTNO={partnoCol}, MATERIAL={materialCol}, DESC={descCol}, QTY={qtyCol}, CUTLIST={cutListCol}, CONFIG={configCol}");

// Collect PLATE rows
var plateRows = new System.Collections.Generic.List<(string partno, string config, string cutList, string modelPath, string material, string description, string qty)>();
for (int r = headerCount; r < rowCount; r++)
{
    string partno = "", material = "", cutList = "", config = "", modelPath = "", description = "", qty = "";
    try { partno = tableAnnot.get_DisplayedText2(r, partnoCol, false) ?? ""; } catch { }
    try { material = materialCol >= 0 ? (tableAnnot.get_DisplayedText2(r, materialCol, false) ?? "") : ""; } catch { }
    try { cutList = cutListCol >= 0 ? (tableAnnot.get_DisplayedText2(r, cutListCol, false) ?? "") : ""; } catch { }
    try { config = configCol >= 0 ? (tableAnnot.get_DisplayedText2(r, configCol, false) ?? "") : ""; } catch { }
    try { description = descCol >= 0 ? (tableAnnot.get_DisplayedText2(r, descCol, false) ?? "") : ""; } catch { }
    try { qty = qtyCol >= 0 ? (tableAnnot.get_DisplayedText2(r, qtyCol, false) ?? "") : ""; } catch { }

    try
    {
        int pc = bomAnnot.GetModelPathNamesCount(r);
        if (pc > 0)
        {
            string iN, pN;
            var paths = (string[])bomAnnot.GetModelPathNames(r, out iN, out pN);
            if (paths != null && paths.Length > 0) modelPath = paths[0];
        }
    }
    catch { }

    string matUpper = material.ToUpper();
    if ((matUpper.Contains("PLATE") || matUpper.Contains("SHEET")) && !string.IsNullOrEmpty(partno))
        plateRows.Add((partno, config, cutList, modelPath, material, description, qty));
}

// Delete BOM
try
{
    var feat = (Feature)bomFeat.GetFeature();
    feat.Select2(false, 0);
    activeDoc.DeleteSelection(false);
}
catch { }

Console.WriteLine($"Found {plateRows.Count} PLATE rows");

// === PHASE 2: Export DXFs ===
int success = 0, fail = 0;
var warnings = new System.Collections.Generic.List<string>();
var usedNames = new System.Collections.Generic.Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);

foreach (var row in plateRows)
{
    Console.Write($"{row.partno}...");

    if (string.IsNullOrEmpty(row.modelPath))
    {
        warnings.Add($"{row.partno}: No model path");
        fail++;
        Console.WriteLine(" SKIP-nopath");
        continue;
    }

    // Open part
    ModelDoc2 partModel = null;
    try
    {
        int errs = 0, wrns = 0;
        partModel = (ModelDoc2)swApp.OpenDoc6(row.modelPath, 1, 1, "", ref errs, ref wrns);
    }
    catch { }
    if (partModel == null)
    {
        try { partModel = (ModelDoc2)swApp.GetOpenDocumentByName(row.modelPath); } catch { }
    }
    if (partModel == null)
    {
        warnings.Add($"{row.partno}: Can't open '{row.modelPath}'");
        fail++;
        Console.WriteLine(" FAIL-open");
        continue;
    }

    // Activate part
    int ae = 0;
    swApp.ActivateDoc3(partModel.GetTitle(), false, 0, ref ae);

    // Set configuration
    if (!string.IsNullOrEmpty(row.config))
        partModel.ShowConfiguration2(row.config);

    // Detect document units: swMM=0, swCM=1, swMETER=2, swINCHES=3, swFEET=4, swFEETINCHES=5
    int docUnit = 3; // default to inches
    try { docUnit = partModel.LengthUnit; } catch { }

    var partDoc = (PartDoc)partModel;
    object[] bodies = null;
    try { bodies = (object[])partDoc.GetBodies2(0, true); } catch { }

    if (bodies == null || bodies.Length == 0)
    {
        warnings.Add($"{row.partno}: No visible bodies");
        fail++;
        Console.WriteLine(" FAIL-nobodies");
        swApp.ActivateDoc3(assyTitle, false, 0, ref ae);
        continue;
    }

    Body2 targetBody = null;
    bool isSheetMetal = false;

    if (bodies.Length == 1)
    {
        targetBody = (Body2)bodies[0];
        isSheetMetal = targetBody.IsSheetMetal();
    }
    else if (!string.IsNullOrEmpty(row.cutList))
    {
        // Multi-body weldment: find cut list folder (wrapped in try/catch for COM resilience)
        try
        {
            var feat = (Feature)partModel.FirstFeature();
            while (feat != null && targetBody == null)
            {
                try
                {
                    // Check this feature
                    if (feat.GetTypeName2() == "CutListFolder" && feat.Name == row.cutList)
                    {
                        var bf = (BodyFolder)feat.GetSpecificFeature2();
                        if (bf != null)
                        {
                            var clBodies = bf.GetBodies();
                            if (clBodies != null)
                            {
                                var arr = (object[])clBodies;
                                if (arr.Length > 0)
                                {
                                    targetBody = (Body2)arr[0];
                                    isSheetMetal = targetBody.IsSheetMetal();
                                }
                            }
                        }
                    }

                    // Check sub-features
                    var sub = (Feature)feat.GetFirstSubFeature();
                    while (sub != null && targetBody == null)
                    {
                        try
                        {
                            if (sub.GetTypeName2() == "CutListFolder" && sub.Name == row.cutList)
                            {
                                var bf = (BodyFolder)sub.GetSpecificFeature2();
                                if (bf != null)
                                {
                                    var clBodies = bf.GetBodies();
                                    if (clBodies != null)
                                    {
                                        var arr = (object[])clBodies;
                                        if (arr.Length > 0)
                                        {
                                            targetBody = (Body2)arr[0];
                                            isSheetMetal = targetBody.IsSheetMetal();
                                        }
                                    }
                                }
                            }
                        }
                        catch { }
                        try { sub = (Feature)sub.GetNextSubFeature(); } catch { sub = null; }
                    }
                }
                catch { }
                try { feat = (Feature)feat.GetNextFeature(); } catch { feat = null; }
            }
        }
        catch (Exception ex) { warnings.Add($"{row.partno}: cut list walk error: {ex.Message}"); }

        if (targetBody == null)
        {
            warnings.Add($"{row.partno}: Cut list '{row.cutList}' not found (bodies={bodies.Length})");
            fail++;
            Console.WriteLine($" FAIL-cutlist");
            swApp.ActivateDoc3(assyTitle, false, 0, ref ae);
            continue;
        }
    }
    else
    {
        // Multi-body, no cut list name - warn and skip
        warnings.Add($"{row.partno}: Multi-body ({bodies.Length}) but no cut list name");
        fail++;
        Console.WriteLine(" WARN-multibody");
        swApp.ActivateDoc3(assyTitle, false, 0, ref ae);
        continue;
    }

    // Build descriptive DXF filename:
    // <material> <partno> (<qty> per kit) <description>.dxf

    // Sanitize material: replace " with " in ", / and . with -, : with -
    string matClean = row.material
        .Replace("\"", " in ")
        .Replace("/", "-")
        .Replace(".", "-")
        .Replace(":", "-");

    // Truncate description to 32 chars, add dash if truncated
    string descClean = row.description.Trim();
    if (descClean.Length > 32)
        descClean = descClean.Substring(0, 32).TrimEnd() + "-";

    // Build filename
    string qtyStr = string.IsNullOrEmpty(row.qty) ? "1" : row.qty.Trim();
    string safeName;
    if (!string.IsNullOrEmpty(descClean))
        safeName = $"{matClean} {row.partno} ({qtyStr} per kit) {descClean}";
    else
        safeName = $"{matClean} {row.partno} ({qtyStr} per kit)";

    // Remove illegal filename chars (keep what we've already handled, discard the rest)
    foreach (char c in System.IO.Path.GetInvalidFileNameChars())
        safeName = safeName.Replace(c.ToString(), "");

    // Collapse multiple spaces to single, trim
    while (safeName.Contains("  "))
        safeName = safeName.Replace("  ", " ");
    safeName = safeName.Trim();

    // Check total path length (Windows 260 limit, leave margin)
    string testPath = System.IO.Path.Combine(outputDir, safeName + "_raw.dxf");
    if (testPath.Length > 250 && descClean.Length > 0)
    {
        // Shorten description to fit
        int excess = testPath.Length - 250;
        int newLen = Math.Max(0, descClean.Length - excess - 1);
        if (newLen > 0)
            descClean = descClean.Substring(0, newLen).TrimEnd() + "-";
        else
            descClean = "";
        if (!string.IsNullOrEmpty(descClean))
            safeName = $"{matClean} {row.partno} ({qtyStr} per kit) {descClean}";
        else
            safeName = $"{matClean} {row.partno} ({qtyStr} per kit)";
        while (safeName.Contains("  "))
            safeName = safeName.Replace("  ", " ");
        safeName = safeName.Trim();
    }

    // Detect PARTNO conflicts (use partno as the conflict key)
    string conflictKey = row.partno;
    if (usedNames.ContainsKey(conflictKey))
    {
        int conflictNum = usedNames[conflictKey];
        usedNames[conflictKey] = conflictNum + 1;

        // On first collision, rename the original file too
        if (conflictNum == 1)
        {
            // Find and rename the first file that starts with this partno's pattern
            try
            {
                string[] existing = System.IO.Directory.GetFiles(outputDir, "*.dxf");
                foreach (string ef in existing)
                {
                    string efName = System.IO.Path.GetFileName(ef);
                    if (efName.Contains(conflictKey) && !efName.StartsWith("conflict"))
                    {
                        string renamedPath = System.IO.Path.Combine(outputDir, $"conflict00_{efName}");
                        System.IO.File.Move(ef, renamedPath);
                        warnings.Add($"{conflictKey}: Duplicate PARTNO — original renamed to conflict00_{efName}");
                        break;
                    }
                }
            }
            catch { }
        }

        safeName = $"conflict{conflictNum:D2}_{safeName}";
        warnings.Add($"{row.partno}: Duplicate PARTNO — saved as {safeName}.dxf");
        Console.Write($" [CONFLICT]");
    }
    else
    {
        usedNames[conflictKey] = 1;
    }
    string rawDxfPath = System.IO.Path.Combine(outputDir, safeName + "_raw.dxf");
    string cleanDxfPath = System.IO.Path.Combine(outputDir, safeName + ".dxf");
    bool exported = false;

    if (isSheetMetal)
    {
        // Sheet metal: use flat pattern export directly (no cleanup needed)
        double[] align = { 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1 };
        try { exported = partDoc.ExportToDWG2(cleanDxfPath, partModel.GetPathName(), 1, true, (object)align, false, false, 1, null); }
        catch (Exception ex) { warnings.Add($"{row.partno}: SheetMetal export error: {ex.Message}"); }
        Console.Write($" SM={exported}");
    }
    else
    {
        // === VIEW-BASED EXPORT ===

        // Step 1: Find largest flat face (for view orientation)
        object[] faces = null;
        try { faces = (object[])targetBody.GetFaces(); } catch { }

        Face2 bestFace = null;
        double bestArea = 0;

        if (faces != null)
        {
            foreach (var fObj in faces)
            {
                try
                {
                    var face = (Face2)fObj;
                    var surf = (Surface)face.GetSurface();
                    if (surf != null && surf.IsPlane())
                    {
                        double area = face.GetArea();
                        if (area > bestArea)
                        {
                            bestArea = area;
                            bestFace = face;
                        }
                    }
                }
                catch { }
            }
        }

        if (bestFace == null)
        {
            warnings.Add($"{row.partno}: No flat faces on target body");
            fail++;
            Console.WriteLine(" FAIL-noflat");
            swApp.ActivateDoc3(assyTitle, false, 0, ref ae);
            continue;
        }

        // Step 2: Multi-body isolation - hide all bodies except targetBody
        var hiddenBodies = new System.Collections.Generic.List<Body2>();
        if (bodies.Length > 1)
        {
            foreach (var bObj in bodies)
            {
                var b = (Body2)bObj;
                if (b != targetBody)
                {
                    try { b.HideBody(true); hiddenBodies.Add(b); } catch { }
                }
            }
            if (hiddenBodies.Count > 0)
                Console.Write($" [isolated:{hiddenBodies.Count}hidden]");
        }

        // Step 3: Detect tapped holes on the target body BEFORE hiding other bodies
        // (walking the full feature tree requires all bodies visible for face-feature lookups)
        var tappedHoles = new System.Collections.Generic.List<(double x, double y, double z, double dia)>();
        try
        {
            // Build a set of face IDs belonging to targetBody for fast lookup
            var targetFaceIds = new System.Collections.Generic.HashSet<int>();
            var tbFaces = (object[])targetBody.GetFaces();
            if (tbFaces != null)
            {
                foreach (var fo in tbFaces)
                {
                    try { targetFaceIds.Add(((Face2)fo).GetFaceId()); } catch { }
                }
            }

            // Walk features to find Hole Wizard features with tapped holes
            var scanFeat = (Feature)partModel.FirstFeature();
            while (scanFeat != null)
            {
                try
                {
                    string ftype = scanFeat.GetTypeName2();
                    if (ftype == "HoleWzd")
                    {
                        var hwData = scanFeat.GetDefinition() as WizardHoleFeatureData2;
                        if (hwData != null)
                        {
                            try { hwData.AccessSelections(partModel, null); } catch { }
                            double tapDia = hwData.TapDrillDiameter;
                            double thruTapDia = hwData.ThruTapDrillDiameter;
                            double threadDia = hwData.ThreadDiameter;
                            bool isTapped = (tapDia > 0 || thruTapDia > 0 || threadDia > 0);
                            double holeDia = tapDia > 0 ? tapDia : (thruTapDia > 0 ? thruTapDia : threadDia);
                            try { hwData.ReleaseSelectionAccess(); } catch { }

                            if (isTapped && holeDia > 0)
                            {
                                // Get the feature's cylindrical faces belonging to targetBody
                                var featFaces = (object[])scanFeat.GetFaces();
                                if (featFaces != null)
                                {
                                    foreach (var fo in featFaces)
                                    {
                                        try
                                        {
                                            var face = (Face2)fo;
                                            // Only consider faces on the target body (for multi-body parts)
                                            if (!targetFaceIds.Contains(face.GetFaceId())) continue;
                                            var surf = (Surface)face.GetSurface();
                                            if (surf != null && surf.IsCylinder())
                                            {
                                                double[] cp = (double[])surf.CylinderParams;
                                                // cp layout: [0-2]=root, [3-5]=axis, [6]=radius
                                                if (cp != null && cp.Length >= 7)
                                                {
                                                    double faceRadius = cp[6];
                                                    // Match radius to hole diameter (radius within 20% of expected)
                                                    double expectedRadius = holeDia / 2.0;
                                                    if (Math.Abs(faceRadius - expectedRadius) / expectedRadius < 0.2)
                                                    {
                                                        tappedHoles.Add((cp[0], cp[1], cp[2], holeDia));
                                                    }
                                                }
                                            }
                                        }
                                        catch { }
                                    }
                                }
                            }
                        }
                    }
                    else if (ftype == "CThread")
                    {
                        // Cosmetic thread feature
                        var ctData = scanFeat.GetDefinition() as CosmeticThreadFeatureData;
                        if (ctData != null)
                        {
                            try { ctData.AccessSelections(partModel, null); } catch { }
                            double ctDia = ctData.Diameter;
                            var edge = ctData.Edge;
                            try { ctData.ReleaseSelectionAccess(); } catch { }

                            if (edge != null && ctDia > 0)
                            {
                                try
                                {
                                    var e = (Edge)edge;
                                    var curve = (Curve)e.GetCurve();
                                    if (curve != null && curve.IsCircle())
                                    {
                                        double[] circParams = (double[])curve.CircleParams;
                                        // CircleParams: [0-2]=center, [3-5]=axis, [6]=radius
                                        if (circParams != null && circParams.Length >= 7)
                                        {
                                            // Check edge's face is on targetBody
                                            var eFaces = (object[])e.GetTwoAdjacentFaces2();
                                            bool onTarget = false;
                                            if (eFaces != null)
                                            {
                                                foreach (var efo in eFaces)
                                                {
                                                    if (efo != null && targetFaceIds.Contains(((Face2)efo).GetFaceId()))
                                                    {
                                                        onTarget = true;
                                                        break;
                                                    }
                                                }
                                            }
                                            if (onTarget)
                                                tappedHoles.Add((circParams[0], circParams[1], circParams[2], ctDia));
                                        }
                                    }
                                }
                                catch { }
                            }
                        }
                    }
                }
                catch { }
                try { scanFeat = (Feature)scanFeat.GetNextFeature(); } catch { scanFeat = null; }
            }
        }
        catch (Exception ex) { warnings.Add($"{row.partno}: tapped detection error: {ex.Message}"); }

        if (tappedHoles.Count > 0)
            Console.Write($" [tapped:{tappedHoles.Count}]");

        // Step 4: Orient view normal to face
        partModel.ClearSelection2(true);
        try { ((Entity)bestFace).Select4(false, null); } catch { }
        try { swApp.RunCommand(169, ""); } catch { } // swCommands_NormalTo = 169
        partModel.ViewZoomtofit2();

        // Project tapped holes to 2D view coordinates using ModelView.Orientation3
        var projectedTappedHoles = new System.Collections.Generic.List<(double u, double v, double dia)>();
        if (tappedHoles.Count > 0)
        {
            try
            {
                var mv = (ModelView)partModel.ActiveView;
                var orient = (MathTransform)mv.Orientation3;
                var mu = (MathUtility)swApp.GetMathUtility();
                foreach (var th in tappedHoles)
                {
                    try
                    {
                        double[] ptArr = new double[3] { th.x, th.y, th.z };
                        var pt = (MathPoint)mu.CreatePoint(ptArr);
                        var transformed = (MathPoint)pt.MultiplyTransform(orient);
                        var tArr = (double[])transformed.ArrayData;
                        projectedTappedHoles.Add((tArr[0], tArr[1], th.dia));
                    }
                    catch { }
                }
            }
            catch (Exception ex) { warnings.Add($"{row.partno}: tapped projection error: {ex.Message}"); }
        }

        // Step 5: Export projected view as raw DXF
        double[] align = { 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1 };
        string[] views = new string[] { "*Current" };
        partModel.ClearSelection2(true); // deselect face before export
        try { exported = partDoc.ExportToDWG2(rawDxfPath, partModel.GetPathName(), 3, true, (object)align, false, false, 0, (object)views); }
        catch (Exception ex) { warnings.Add($"{row.partno}: View export error: {ex.Message}"); }
        Console.Write($" A={bestArea * 1e6:F0}mm2 raw={exported}");

        // Step 6: Restore hidden bodies
        foreach (var b in hiddenBodies)
        {
            try { b.HideBody(false); } catch { }
        }

        // Step 7: Always write a sidecar file (even if no tapped holes)
        // First line is "#unit=N" so the Python wrapper can configure cleanup tolerances.
        // Remaining lines are tapped hole positions: u,v,diameter
        string tappedSidecar = System.IO.Path.Combine(outputDir, safeName + "_tapped.txt");
        try
        {
            var sb = new System.Text.StringBuilder();
            sb.AppendLine($"#unit={docUnit}");
            foreach (var th in projectedTappedHoles)
                sb.AppendLine($"{th.u:F6},{th.v:F6},{th.dia:F6}");
            System.IO.File.WriteAllText(tappedSidecar, sb.ToString());
        }
        catch (Exception ex) { warnings.Add($"{row.partno}: sidecar write error: {ex.Message}"); }
    }

    if (exported)
    {
        success++;
        Console.WriteLine(" OK");
    }
    else
    {
        fail++;
        if (!warnings.Exists(w => w.StartsWith(row.partno)))
            warnings.Add($"{row.partno}: ExportToDWG2 returned false");
        Console.WriteLine(" FAIL-export");
    }

    // Close the part window without saving (no prompt, assembly keeps its reference)
    try { swApp.QuitDoc(partModel.GetTitle()); } catch { }
    swApp.ActivateDoc3(assyTitle, false, 0, ref ae);
}

// === SUMMARY ===
Console.WriteLine($"\n========================================");
Console.WriteLine($"=== RESULTS ===");
Console.WriteLine($"Total PLATE: {plateRows.Count}");
Console.WriteLine($"Success: {success}");
Console.WriteLine($"Failed: {fail}");

Console.WriteLine($"\n>>> WARNING: REVIEW ALL DXFs BEFORE SENDING TO PLASMA TABLE <<<");

if (warnings.Count > 0)
{
    Console.WriteLine($"\nWARNINGS ({warnings.Count}):");
    foreach (var w in warnings)
        Console.WriteLine($"  ! {w}");
}
Console.WriteLine($"========================================");
Console.WriteLine("---DONE---");
