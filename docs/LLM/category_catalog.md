# ScripTree Category Catalog — canonical taxonomy

<!-- Generated for v0.8.0a111. Companion machine-readable file: `scriptree/resources/category_catalog.json`. Read `category_authoring.md` for the field mechanics; THIS file is the controlled vocabulary. -->

This is the RECOMMENDED controlled vocabulary for ScripTree's `category` field — the canonical list of category paths the catalog already uses (807 paths across ~190 top-level segments such as SolidWorks, MSOffice, Media, AutoCAD, Adobe, QGIS, PostgreSQL, AWS, and so on). Free-form categories are still allowed (the loader never rejects a path, it only sanitises slashes), but staying on-list is strongly preferred: the forest folds tools that share a TOP segment into one cell, so reusing an existing top-level brand/domain keeps related tools together instead of fragmenting the hub into near-duplicate cells (e.g. SolidWorks vs Solidworks vs SW). Treat this list as the default vocabulary; reach for a new segment only when nothing on-list fits, and follow the conventions below so the new path stays consistent with the rest.

**This catalog lists 799 recommended categories across 185 top-level domains.** It is the *recommended* controlled vocabulary — `category` is still free-form, but staying on-list keeps the forest from fragmenting into near-duplicate cells. `python -m scriptree validate` warns (advisory, never blocks) when a category is a near-duplicate of a catalog entry or of a sibling in the same forest.

## How to choose a category

1. 1. Identify the tool's TARGET. Does it drive ONE specific commercial application (SolidWorks, Word, Photoshop, QGIS, AutoCAD)? If yes, use the Vendor/App pattern. If it's a general-purpose or cross-app workflow tool (git, ffmpeg, SQL, file utilities), use the Domain/Sub pattern.
1. 2. Pick the TOP segment from the existing list FIRST. Scan the 190 shipped top-levels for the brand or domain that matches. If the tool targets SolidWorks, the top is SolidWorks — full stop. Only mint a NEW top segment if nothing on-list covers the target, and only if you expect it to grow more than one tool.
1. 3. Pick the SUB-area. For a known top (e.g. SolidWorks, MSOffice), reuse an existing sub-area if one fits (SolidWorks/Drawings, MSOffice/Excel). Match the established sub-areas exactly — do not coin SolidWorks/Drawing when SolidWorks/Drawings already exists.
1. 4. If no existing sub-area fits, add a new Title Case sub-area that names the FUNCTIONAL AREA (what the tool acts on: Export, BOM, References, Layers, Macros), not the tool's own name.
1. 5. Check DEPTH. Aim for 2 segments. Add a third only when the second would otherwise collect a sprawl of unrelated tools (e.g. SolidWorks/Performance/Assembly). Never exceed 4.
1. 6. Apply the GROWTH test: would a second, third, fifth tool plausibly share this exact top segment? If the top is a one-off tool name, you chose wrong — promote to the brand/domain it belongs under, or omit the category entirely for a true standalone.
1. 7. Verify CASING and SPELLING against the list: no spaces in brand tops, Title Case sub-areas, exact reuse of an existing segment's casing. A new path that only differs from an existing one by case or pluralisation is a fragmentation bug — reconcile to the existing form.
1. 8. Validate: run `python -m scriptree validate <path>` from D:\Dev\ScripTree. The loader sanitises slashes silently, so a malformed path won't error — eyeball the stored value to confirm it matches what you intended.

## Conventions

- A category is a SLASH-DELIMITED path with forward slashes only: <Top>/<Sub>/<Sub>. No leading/trailing slash, no empty segments, no OS backslashes (the loader sanitises these but don't rely on it).
- Title Case every segment. Brand/app top-levels carry NO spaces (MSOffice, SolidWorks, Fusion360, ArcGIS, PowerBI); multi-word sub-areas are Title Case (Performance/Assembly, Capital Gains).
- TWO patterns: (a) <Vendor>/<App>/<Area> for tools that drive a specific commercial app — the TOP segment is the vendor/app brand (SolidWorks/Drawings, MSOffice/Word, Adobe/Photoshop, AutoCAD/Layers); (b) <Domain>/<Sub> for general-purpose / cross-app workflow tools (DevTools/Git, Media/Video, Data/SQL, System/Files).
- The TOP segment should be the thing likely to GROW — a brand or a broad workflow domain — never a one-off tool name. The forest folds 2+ tools sharing a top segment into one cell, so pick a top that will accumulate siblings.
- DEPTH: 2 levels is the norm, 3 is fine, 4 is the hard cap. Don't over-nest; cell-popup menus with 4+ nested submenus get awkward.
- Segment names are SHORT, STABLE folder/menu labels. Prefer a small number of well-chosen sub-areas per top over a sprawl of near-duplicates.
- Case is preserved for display but compared case-insensitively at the bucket level, so 'MSOffice' and 'msoffice' collide into one tree — pick one casing per top segment and reuse it exactly.
- EXTEND the existing de-facto sub-areas rather than renaming them: Media/ffmpeg; MSOffice/{Word,Excel,Outlook,PowerPoint}; SolidWorks/{Drawings, Performance/{Assembly,Drawing,Process}, System, Export, Assembly, References, BOM}; plus the top-level ScripTree and Demos buckets.
- A category is mandatory metadata for grouped tools (v0.8.0a25+) and safely omittable for a genuine one-off — leave it off rather than inventing a singleton top segment that will never grow.

## Reconciled drift / notes

- Demo + Demos -> Demos (the catalog top-level is Demos; never author a singular 'Demo' top segment).
- Drawing + Drawings -> SolidWorks/Drawings (the established SolidWorks sub-area is plural 'Drawings').
- SW + Solidworks + solidworks -> SolidWorks (one brand top, exact CamelCase casing; case-insensitive bucketing means variants collide but the displayed label should be the canonical SolidWorks).
- MS Office + Ms Office + Office -> MSOffice (brand top has no space and is the canonical container for Word/Excel/Outlook/PowerPoint).
- FFmpeg + FFMPEG + ffmpeg -> Media/ffmpeg (keep the established lowercase 'ffmpeg' sub-area under the Media domain top).
- Fusion 360 + Fusion-360 -> Fusion360 (brand tops carry no spaces or separators).
- `Demo` → **`Demos`** (the shipped catalog had both; `Demos` is canonical).

## The taxonomy

Grouped by domain. Each row is a canonical `category` path and what belongs there.

### Mechanical CAD & PLM

Tools that drive mechanical CAD systems (SolidWorks, Inventor, Fusion 360, AutoCAD, NX, Creo, Onshape and more) plus the PDM/PLM vaults around them — covering modeling, drawings, BOM, exports, properties, configurations, and design-health automation.

| Category | What belongs here |
|---|---|
| `SolidWorks/Drawings` | Drawing-document automation: views, dimensions, annotations, sheet formats, title blocks, revision tables (existing shipped category). |
| `SolidWorks/Assembly` | Assembly-document operations: mates, components, patterns, interference, exploded views, lightweight/large-assembly handling (existing shipped category). |
| `SolidWorks/Parts` | Part-document modeling: features, sketches, equations, mass properties, material assignment, feature-tree edits. |
| `SolidWorks/BOM` | Bill-of-materials generation, extraction, reconciliation, and indented/parts-only/flat BOM exports (existing shipped category). |
| `SolidWorks/Export` | Neutral-format and derivative output: STEP, IGES, Parasolid, STL, DXF/DWG, PDF, eDrawings, images (existing shipped category). |
| `SolidWorks/References` | Reference, link, and pack-and-go management: where-used, replace references, repair broken links, file relocation (existing shipped category). |
| `SolidWorks/System` | Application/system-level utilities: settings, options, templates, toolbox, file-locations, add-in management (existing shipped category). |
| `SolidWorks/Properties` | Custom and configuration-specific property read/write/bulk-edit, property tab schemas, metadata sync. |
| `SolidWorks/Configurations` | Configuration and design-table automation: create/derive configs, drive via design tables, suppress states, configuration cleanup. |
| `SolidWorks/Performance/Assembly` | Assembly performance/health diagnostics: rebuild times, mate health, lightweight ratios, large-assembly mode tuning (existing shipped category). |
| `SolidWorks/Performance/Drawing` | Drawing performance/health: heavy view detection, detached-drawing checks, display-mode optimization (existing shipped category). |
| `SolidWorks/Performance/Process` | Process/session-level performance: SLDWORKS memory, open-file profiling, batch-job throughput monitoring (existing shipped category). |
| `SolidWorks/Batch` | Headless/queued batch operations across many files: batch rebuild, batch print, batch convert, scheduled task runs. |
| `SolidWorks/PDM` | SolidWorks PDM (EPDM) vault automation: check-in/out, state transitions, variable read/write, where-used, vault queries. |
| `Inventor/Parts` | Autodesk Inventor part (.ipt) modeling: features, parameters, iProperties, material, feature-tree automation. |
| `Inventor/Assembly` | Inventor assembly (.iam): constraints, occurrences, BOM, level-of-detail, interference analysis. |
| `Inventor/Drawings` | Inventor drawing (.idw/.dwg) automation: views, dimensions, parts lists, title blocks, sheet output. |
| `Inventor/Export` | Inventor neutral/derivative exports: STEP, IGES, STL, DWF, PDF, shrinkwrap. |
| `Inventor/iLogic` | iLogic rule authoring, parameter-driven automation, rule-triggered batch updates and design configuration. |
| `Fusion360/Design` | Fusion 360 design/modeling automation via the Fusion API: bodies, components, sketches, parameters, timeline. |
| `Fusion360/CAM` | Fusion 360 manufacturing/CAM: toolpath generation, post-processing, setup sheets, NC output. |
| `Fusion360/Export` | Fusion 360 exports and conversions: STEP, IGES, SAT, STL, F3D archive, drawing PDF. |
| `AutoCAD/Drawings` | AutoCAD mechanical drawing automation: layouts, layers, blocks, attributes, plotting, title blocks. |
| `AutoCAD/Data` | AutoCAD data extraction and tables: attribute extraction, data links, BOM/parts tables, CSV round-trip. |
| `AutoCAD/Export` | AutoCAD format conversion and output: DWG<->DXF, PDF, DWF, batch convert, version downgrade. |
| `Creo/Modeling` | PTC Creo part/assembly modeling automation: features, parameters, relations, family tables. |
| `Creo/Export` | Creo neutral/derivative export: STEP, IGES, Parasolid, STL, PDF, drawing output. |
| `NX/Modeling` | Siemens NX modeling and assembly automation via NX Open: features, expressions, components, attributes. |
| `NX/Export` | Siemens NX exports and conversion: STEP, JT, Parasolid, IGES, STL, drawing PDF. |
| `SolidEdge/Modeling` | Solid Edge part/assembly automation: synchronous/ordered features, variables, family of parts. |
| `Onshape/Documents` | Onshape cloud-document automation via REST API: documents, workspaces, versions, configurations, metadata. |
| `Onshape/Export` | Onshape translations and exports: STEP, Parasolid, STL, drawing PDF, blob export via API. |
| `FreeCAD/Modeling` | FreeCAD scripted modeling and document automation via the Python API: parts, sketches, parameters, spreadsheets. |
| `FreeCAD/Export` | FreeCAD format conversion and mesh/CAD export: STEP, IGES, STL, OBJ, DXF, batch convert. |
| `KeyShot/Render` | KeyShot rendering automation: scene import, material/camera setup, batch render, render-queue scripting. |
| `PLM/Teamcenter` | Siemens Teamcenter PLM automation: item/dataset queries, workflow, BOM/structure, attribute sync. |
| `PLM/Windchill` | PTC Windchill PLM automation: object lifecycle, change management, BOM extraction, REST/Info*Engine queries. |
| `PLM/Vault` | Autodesk Vault automation: check-in/out, lifecycle states, property sync, file/folder queries, where-used. |
| `CAD/Convert` | Cross-vendor / format-agnostic CAD conversion and translation between neutral formats (vendor-neutral workflow tools). |
| `CAD/Inspect` | Vendor-neutral model inspection, validation, and geometry comparison: mass props, model diff, quality checks. |

### CAM, CNC & Additive Manufacturing

Tools that drive CAM packages, post-processors and CNC machining workflows, plus the additive-manufacturing slicing, mesh-prep and digital-fabrication (laser/plasma/waterjet) and metrology pipelines around them.

| Category | What belongs here |
|---|---|
| `Mastercam/Toolpaths` | Mastercam milling/turning/router toolpath generation, regeneration and parameter automation. |
| `Mastercam/Posts` | Mastercam post-processor (.pst/.mcpost) editing, switching and post-run automation. |
| `Mastercam/Verify` | Mastercam backplot/Verify simulation, gouge checks and stock-model output. |
| `Fusion360/CAM` | Fusion 360 manufacturing/CAM: toolpath generation, post-processing, setup sheets, NC output. |
| `Fusion360/Posts` | Fusion post-processor (.cps) authoring, editing and the Autodesk post library. |
| `Hexagon/PowerMill/Toolpaths` | Autodesk/Hexagon PowerMill high-speed and multi-axis toolpath automation and macros. |
| `Hexagon/Edgecam/Toolpaths` | Hexagon Edgecam milling/turning strategy automation and Strategy Manager. |
| `GibbsCAM/Toolpaths` | GibbsCAM milling/turning operation and process automation. |
| `SprutCAM/Toolpaths` | SprutCAM operation and robot/multi-axis toolpath automation. |
| `CNC/GCode` | G-code generation, parsing, editing, renumbering and reformatting independent of any one CAM vendor. |
| `CNC/PostProcessors` | Vendor-neutral post-processor build/test/validation and post-output diffing. |
| `CNC/Simulation` | Machine/material-removal simulation and collision checking outside a CAM package. |
| `CNC/DNC` | DNC/drip-feed transfer, serial/RS-232 and program send/receive to machine controls. |
| `CNC/ToolLibrary` | Cutting-tool and tool-assembly library management, import/export and tool data. |
| `CNC/Controls` | Controller-specific utilities and macro handling (Fanuc, Haas, Siemens, Heidenhain, Mazak). |
| `Slicer/Cura` | UltiMaker Cura slicing, profile and CuraEngine batch automation. |
| `Slicer/PrusaSlicer` | PrusaSlicer slicing, config bundles and console-mode batch slicing. |
| `Slicer/OrcaSlicer` | OrcaSlicer slicing, calibration and profile automation. |
| `Slicer/BambuStudio` | Bambu Studio slicing and 3MF project automation. |
| `Slicer/Simplify3D` | Simplify3D process/FFF profile automation and batch slicing. |
| `Additive/Mesh` | STL/3MF/OBJ mesh repair, healing, decimation, remesh and watertight checks. |
| `Additive/Supports` | Support generation, orientation optimization and overhang analysis for FDM/SLA. |
| `Additive/PrinterControl` | Printer host/firmware control, queue management and remote print jobs. |
| `Nesting/Sheet` | Part nesting and sheet-layout optimization for laser/plasma/router/waterjet cut sheets. |
| `DXF/CutPrep` | DXF cleanup, dedup, boundary tracing and lead-in/kerf prep for 2D cutting machines. |
| `Cutting/Laser` | Laser-cutter job prep, control and power/speed parameter automation. |
| `Cutting/Plasma` | Plasma-table CAM, THC settings and G-code prep for plasma cutting. |
| `Cutting/Waterjet` | Waterjet abrasive/feed parameter and cut-order automation. |
| `Metrology/CMM` | CMM program generation, DMIS output and probe-path automation. |
| `Metrology/Inspection` | First-article/inspection reporting, ballooning and GD&T inspection data. |
| `Metrology/ScanData` | 3D-scan point-cloud import, alignment and scan-to-mesh/CAD comparison. |

### CAE, Simulation & Analysis

Tools that drive engineering simulation and analysis software — FEA, CFD, multibody, electromagnetics, optimization, meshing, and the technical-computing environments (MATLAB, Mathematica, Octave) used to set up, run, and post-process those analyses.

| Category | What belongs here |
|---|---|
| `Ansys/Mechanical/Setup` | Build/define structural-FEA models in Ansys Mechanical — materials, contacts, connections, named selections, loads & boundary conditions. |
| `Ansys/Mechanical/Solve` | Launch and monitor Ansys structural/thermal/modal solves, batch submission, restart and license checkout. |
| `Ansys/Mechanical/Results` | Post-process Ansys Mechanical results — stress/strain/fatigue extraction, result animations, report export. |
| `Ansys/Fluent/Setup` | Set up Ansys Fluent CFD cases — boundary conditions, turbulence models, materials, solver settings, journals. |
| `Ansys/Fluent/Solve` | Run and monitor Fluent solves — batch/journal execution, residual monitoring, parallel partitioning. |
| `Ansys/CFX` | Ansys CFX CFD pre/solve/post automation — turbo and rotating-machinery cases, CCL session files. |
| `Ansys/HFSS` | Ansys Electronics Desktop / HFSS high-frequency electromagnetic setup, solve, and S-parameter export. |
| `Ansys/Meshing` | Mesh generation for Ansys workflows — Ansys Meshing, Fluent Meshing, mesh-quality checks and conversion. |
| `Ansys/Workbench` | Project-level Ansys Workbench orchestration — parameter sets, project schematic automation, DesignXplorer DOE. |
| `Abaqus/Setup` | Build Abaqus/CAE models and write input decks — parts, sections, contacts, steps, loads. |
| `Abaqus/Solve` | Submit and monitor Abaqus/Standard and Abaqus/Explicit jobs, restart, user-subroutine compile. |
| `Abaqus/Results` | Extract and post-process Abaqus results from .odb — field/history output, XY data, report generation. |
| `MSCNastran/Solve` | Run MSC/MD Nastran solution sequences (SOL 101/103/108/400) — deck submission and run monitoring. |
| `MSCNastran/Results` | Parse Nastran output — .f06/.op2/.pch readers, eigenvalue and stress recovery, HDF5 export. |
| `Comsol/Modeling` | Build and run COMSOL Multiphysics models — physics interfaces, study setup, batch solve via Java/CLI. |
| `LsDyna/Solve` | Run LS-DYNA explicit/implicit crash and impact analyses — keyword deck submission, MPP/SMP control. |
| `LsDyna/Results` | Post-process LS-DYNA output — d3plot/binout extraction, ASCII history, secondary results. |
| `SolidWorks/Simulation` | Drive SolidWorks Simulation studies — study creation, mesh, loads/fixtures, solve and result plots (extends the existing SolidWorks top-level). |
| `StarCCM/Simulation` | Siemens Simcenter STAR-CCM+ CFD automation — macro-driven case setup, mesh pipeline, batch solve, scene export. |
| `OpenFOAM/Case` | Set up and run OpenFOAM CFD cases — dictionary editing, mesh utilities, solver runs, parallel decomposition. |
| `OpenFOAM/PostProcessing` | OpenFOAM post-processing — function objects, sampling, forces/forceCoeffs, ParaView/foamToVTK export. |
| `CAE/Meshing` | Solver-neutral mesh generation, conversion, repair and quality checks across CAE tools. |
| `CAE/Optimization` | Optimization, DOE and design-of-experiments drivers that wrap simulation solvers in the loop. |
| `CAE/PostProcessing` | General-purpose simulation visualization and field post-processing not tied to one vendor. |
| `Matlab/Scripts` | Run MATLAB scripts/functions headless and pass data in/out for engineering computation. |
| `Matlab/Simulink` | Build, run and batch Simulink models — simulation runs, code generation, model parameter sweeps. |
| `Mathematica/Notebooks` | Evaluate Wolfram Mathematica notebooks and scripts in batch — symbolic/numeric computation and export. |
| `Octave/Scripts` | Run GNU Octave scripts headless as a free MATLAB-compatible compute backend. |

### Electronics & PCB (EDA)

Categories for automating electronics design tools — commercial EDA suites (Altium, KiCad, Eagle, OrCAD/Allegro, Mentor), plus cross-app workflows like Gerber/CAM, BOM, SPICE simulation, and FPGA toolchains.

| Category | What belongs here |
|---|---|
| `Altium/Designer/Schematic` | Schematic capture automation in Altium Designer — netlist export, annotation, ERC, sheet generation. |
| `Altium/Designer/Pcb` | PCB layout automation — design rule checks, layer stack edits, polygon pour, output jobs. |
| `Altium/Designer/Libraries` | Component/footprint/symbol library management and vault sync. |
| `Altium/Designer/Output` | Manufacturing & documentation output generation (Gerber, NC drill, pick-and-place, PDF). |
| `KiCad/Schematic` | KiCad eeschema automation via kicad-cli/Python — netlist, ERC, annotation, schematic plots. |
| `KiCad/Pcb` | KiCad pcbnew automation — DRC, board plotting, layer export, scripted edits. |
| `KiCad/Fabrication` | KiCad fabrication outputs — Gerbers, drill files, position files, fab packages. |
| `KiCad/Libraries` | KiCad symbol/footprint/3D-model library tooling and bulk edits. |
| `Eagle/Schematic` | Autodesk Eagle schematic ULP/script automation — netlist, ERC, sheet ops. |
| `Eagle/Board` | Eagle board layout automation — DRC, autorouter invocation, CAM jobs. |
| `OrCAD/Capture` | Cadence OrCAD Capture schematic automation via TCL/SDK — netlist, BOM, DRC. |
| `OrCAD/Pcb` | OrCAD PCB Editor (Allegro lite) layout automation and output. |
| `Allegro/Layout` | Cadence Allegro PCB layout SKILL/TCL automation — placement, routing checks, constraints. |
| `Allegro/Manufacturing` | Allegro fabrication/assembly outputs — artwork, drill, IPC-2581/ODB++ export. |
| `Mentor/PADS` | Siemens/Mentor PADS schematic and layout automation. |
| `Mentor/Xpedition` | Siemens Xpedition enterprise PCB flow automation (AAIF/scripting). |
| `Xilinx/Vivado` | AMD/Xilinx Vivado FPGA flow automation via TCL — synth, implementation, bitstream. |
| `Intel/Quartus` | Intel Quartus Prime FPGA flow automation — compile, fit, timing, programming. |
| `EDA/Gerber` | Vendor-neutral Gerber/RS-274X viewing, validation, diffing, and conversion. |
| `EDA/CAM` | CAM job processing and panelization across EDA tools. |
| `EDA/Drill` | Excellon/NC drill file generation, inspection, and conversion. |
| `EDA/Bom` | Bill-of-materials generation, consolidation, and supplier-part matching. |
| `EDA/Assembly` | Assembly outputs — pick-and-place/centroid files, paste stencil, IPC-2581/ODB++ data prep. |
| `EDA/Netlist` | Netlist generation, format conversion, and cross-tool comparison. |
| `EDA/Libraries` | Vendor-neutral part/symbol/footprint library tooling and 3D model management. |
| `EDA/DesignRules` | Standalone DRC/ERC/DFM rule checking and manufacturability reports. |
| `Spice/Simulation` | SPICE circuit simulation runners and batch sweeps (ngspice, LTspice, Xyce). |
| `Spice/Analysis` | Post-simulation waveform/result processing — plotting, measurements, Monte Carlo. |
| `Embedded/Toolchain` | Firmware build toolchains — cross-compilers, build systems, makefiles for MCUs. |
| `Embedded/Flashing` | Firmware programming and flashing tools for MCUs and dev boards. |
| `Embedded/Debug` | On-target debug, JTAG/SWD bridges, and serial/log capture. |
| `Fpga/Synthesis` | Vendor-neutral / open FPGA synthesis flows and HDL toolchains. |

### AEC, BIM & Civil

Automation categories for architecture, engineering, construction, BIM, and civil/infrastructure tools — spanning Autodesk, Bentley, Graphisoft, and Trimble apps plus cross-app openBIM, surveying, point-cloud, and quantity-takeoff workflows.

| Category | What belongs here |
|---|---|
| `Revit/Models` | Revit document/model-level automation: open, audit, purge, upgrade, detach, worksharing/central-file operations. |
| `Revit/Families` | Revit family (.rfa) creation, batch-loading, parameter editing, type catalogs, and library management. |
| `Revit/Sheets` | Sheets, views, viewports, titleblocks, revision clouds, and view-placement automation. |
| `Revit/Schedules` | Revit schedules and quantity/material takeoff tables: build, export, and round-trip schedule data. |
| `Revit/Parameters` | Shared/project/global parameters and parameter-mapping: bind, populate, transfer parameter definitions. |
| `Revit/MEP` | Revit MEP systems — ductwork, piping, electrical, fixtures, and system browser automation. |
| `Revit/Structure` | Revit structural elements — framing, rebar, analytical model, and connection automation. |
| `Revit/Export` | Revit export pipelines: IFC, DWG, NWC, PDF, and image batch export with mapping/setup control. |
| `AutoCAD/Drawings` | AutoCAD mechanical drawing automation: layouts, layers, blocks, attributes, plotting, title blocks. |
| `AutoCAD/Layers` | Layer standards, layer states, CAD-standards checking, and layer translation/remapping. |
| `AutoCAD/Blocks` | Block definitions, attribute extraction/edit, dynamic blocks, and block library batch insertion. |
| `AutoCAD/Plot` | Plotting and publishing: page setups, plot styles (CTB/STB), batch plot to PDF/DWF. |
| `AutoCAD/Convert` | DWG/DXF version conversion, DWG-to-PDF, and cross-format CAD translation. |
| `Civil3D/Surfaces` | Civil 3D surfaces — TIN/grid surface build, volume calcs, surface analysis and editing. |
| `Civil3D/Alignments` | Civil 3D horizontal/vertical alignments and profiles — create, edit, and report stationing. |
| `Civil3D/Corridors` | Civil 3D corridors, assemblies, and subassemblies — build, rebuild, and extract corridor solids. |
| `Civil3D/Pipes` | Civil 3D pipe and pressure networks — gravity/pressure pipes, structures, and network analysis. |
| `Civil3D/Points` | Civil 3D COGO points and point groups — import survey data, point group rules, description keys. |
| `Civil3D/Grading` | Civil 3D grading objects, feature lines, and grading groups — earthwork and site grading automation. |
| `Navisworks/Clash` | Navisworks clash detection — run clash tests, manage rules, and export clash reports. |
| `Navisworks/Models` | Navisworks model aggregation/append, NWC/NWD/NWF management, and file federation. |
| `Navisworks/Timeliner` | Navisworks TimeLiner 4D scheduling and Quantification 5D takeoff automation. |
| `ArchiCAD/Models` | Graphisoft ArchiCAD project/model automation — teamwork, libraries, and document operations. |
| `ArchiCAD/Export` | ArchiCAD export pipelines — IFC, BIMx, PDF, and DWG batch export with translator control. |
| `Bentley/MicroStation` | Bentley MicroStation DGN automation — levels, cells, references, and batch processing. |
| `Bentley/OpenRoads` | Bentley OpenRoads/OpenRail civil design — geometry, terrain, corridors, and superelevation. |
| `Tekla/Structures` | Trimble Tekla Structures steel/concrete detailing — model objects, numbering, and reports. |
| `Tekla/Export` | Tekla export and interoperability — IFC, NC/DSTV, BVBS, and drawing batch export. |
| `SketchUp/Models` | Trimble SketchUp model automation via Ruby API — geometry, components, materials, scenes. |
| `BIM/IFC` | Vendor-neutral openBIM/IFC tooling — validate, convert, split/merge, and query IFC models. |
| `BIM/BCF` | BIM Collaboration Format (BCF) issue exchange — import, export, and merge BCF issue sets. |
| `BIM/COBie` | COBie facility-handover data — extract, validate, and format COBie spreadsheets from BIM models. |
| `BIM/Standards` | BIM standards and model-checking — naming conventions, LOD checks, and ISO 19650 compliance. |
| `Survey/Data` | Survey data processing — total-station/GNSS field data, raw observations, coordinate transforms. |
| `Survey/PointCloud` | Point-cloud processing — registration, decimation, classification, and format conversion (LAS/E57/RCP). |
| `Survey/GIS` | GIS and geospatial interchange for AEC — shapefile/GeoJSON, georeferencing, and CAD-GIS bridging. |
| `Construction/Takeoff` | Quantity takeoff and estimating across formats — measure, count, and roll up quantities to cost. |

### GIS, Mapping & Surveying

Tools that automate GIS desktop apps, geospatial CLIs, and spatial databases — building, transforming, projecting, analyzing, and serving vector, raster, and point-cloud map data.

| Category | What belongs here |
|---|---|
| `QGIS/Processing` | Headless QGIS processing-algorithm and model runs driven via PyQGIS / qgis_process. |
| `QGIS/Layout` | Automated map-layout / print-composer export to PDF, PNG, or atlas pages. |
| `QGIS/Plugins` | QGIS plugin install, packaging, and repository management. |
| `ArcGIS/ArcPy/Geoprocessing` | Esri ArcGIS geoprocessing-tool runs and ModelBuilder workflows scripted with ArcPy. |
| `ArcGIS/ArcPy/DataManagement` | Feature-class, geodatabase, and table management in ArcGIS via ArcPy. |
| `ArcGIS/Pro/Mapping` | ArcGIS Pro project (.aprx), layout, and symbology automation. |
| `ArcGIS/Online/Publishing` | Publishing and managing hosted layers and web maps on ArcGIS Online / Portal. |
| `GDAL/Raster` | GDAL raster translation, warping, mosaicking, and band math. |
| `GDAL/Vector` | OGR vector format conversion, SQL filtering, and geometry ops. |
| `GDAL/Tiling` | Raster tiling and overview/pyramid generation for web delivery. |
| `GDAL/Info` | Metadata, statistics, and footprint inspection for raster/vector datasets. |
| `GRASS/Processing` | GRASS GIS module runs and mapset/location management for raster & vector analysis. |
| `GeoServer/Publishing` | GeoServer workspace, store, and layer configuration via the REST API. |
| `MapServer/Publishing` | UMN MapServer mapfile generation and WMS/WFS service setup. |
| `PostGIS/Import` | Loading shapefiles, rasters, and OSM into a PostGIS-enabled Postgres database. |
| `PostGIS/Query` | Spatial SQL queries, indexing, and geometry validation against PostGIS. |
| `PostGIS/Export` | Exporting PostGIS tables/queries out to file or web formats. |
| `GeoData/Convert` | General format conversion among shapefile, GeoJSON, KML, GPKG, GML. |
| `GeoData/Projection` | CRS reprojection, datum transforms, and projection inspection. |
| `GeoData/Validate` | Geometry repair, topology checks, and dataset integrity validation. |
| `GeoData/Simplify` | Geometry simplification, generalization, and coordinate precision reduction. |
| `Geocoding/Forward` | Address-to-coordinate geocoding, batch and single. |
| `Geocoding/Reverse` | Coordinate-to-address reverse geocoding and place lookup. |
| `LiDAR/PointCloud` | LiDAR / point-cloud filtering, classification, and ground extraction. |
| `LiDAR/Convert` | Point-cloud format conversion and tiling (LAS/LAZ/COPC/EPT). |
| `Raster/Analysis` | Raster terrain and map-algebra analysis — slope, hillshade, contours, NDVI. |
| `Raster/Mosaic` | Multi-tile mosaicking, color-balancing, and seamline compositing. |
| `Vector/Overlay` | Vector overlay analysis — clip, intersect, union, dissolve, buffer. |
| `Tiles/Vector` | Vector-tile generation and serving (MBTiles / PMTiles / MVT). |
| `Tiles/Serve` | Local/edge tile servers and tileset packaging for web maps. |
| `OSM/Extract` | OpenStreetMap PBF extraction, filtering, and clipping by area or tag. |
| `OSM/Import` | Loading OSM data into a routing or PostGIS database. |
| `Routing/Network` | Network routing, isochrones, and travel-time matrices. |
| `Survey/Coordinates` | Survey coordinate conversion, geodetic computations, and grid-to-ground. |
| `Survey/Field` | Field-survey data import and export — GPX, GNSS, total-station, CSV points. |

### Office & Productivity

Tools that automate office documents and productivity apps — Microsoft Office and LibreOffice via COM/UNO, Google Workspace, and cross-app PDF, mail-merge, and document-generation workflows.

| Category | What belongs here |
|---|---|
| `MSOffice/Word` | Microsoft Word document automation — formatting, styles, find/replace, splitting, revisions. |
| `MSOffice/Word/MailMerge` | Word mail-merge runs: bind a data source, merge to documents/print/email, split per-record output. |
| `MSOffice/Excel` | Excel workbook automation — cell/range edits, sheet ops, formula and value transforms. |
| `MSOffice/Excel/Convert` | Convert workbooks to/from other formats (CSV, PDF, JSON) and bulk-export sheets. |
| `MSOffice/Excel/Macros` | VBA macro and add-in management for Excel — list, run, import/export, strip macros. |
| `MSOffice/PowerPoint` | PowerPoint deck automation — slide/asset cleanup, template apply, export. |
| `MSOffice/Outlook` | Outlook mail/calendar/contact automation — extract, export, bulk-process items. |
| `MSOffice/Access` | Access database automation — query runs, table import/export, report generation. |
| `MSOffice/Visio` | Visio diagram automation — shape/page export, stencil ops, batch conversion. |
| `MSOffice/Project` | Microsoft Project plan automation — task/resource export, schedule conversion. |
| `MSOffice/OneNote` | OneNote notebook automation — page/section export, content extraction. |
| `MSOffice/Publisher` | Microsoft Publisher automation — publication export and batch conversion. |
| `LibreOffice/Writer` | LibreOffice Writer automation via UNO/headless — document conversion and editing. |
| `LibreOffice/Calc` | LibreOffice Calc automation — spreadsheet conversion and batch processing via UNO/headless. |
| `LibreOffice/Impress` | LibreOffice Impress automation — presentation conversion and export. |
| `LibreOffice/Convert` | Generic soffice --headless conversion across any LibreOffice-supported format. |
| `Google/Docs` | Google Docs automation via Apps Script/Drive API — export, templating, batch edits. |
| `Google/Sheets` | Google Sheets automation — data push/pull, range ops, export via Sheets/Drive API. |
| `Google/Slides` | Google Slides automation — deck generation, export, template fill via API. |
| `Google/Drive` | Google Drive file operations — bulk upload/download, conversion, sharing/permissions. |
| `Adobe/Acrobat` | Adobe Acrobat PDF automation via COM/Action Wizard — OCR, optimize, export, combine. |
| `PDF/Merge` | Combine, split, and reorder PDF pages with engine-agnostic CLI tools. |
| `PDF/Forms` | Fill, flatten, and extract PDF AcroForm/XFA form fields. |
| `PDF/Optimize` | Compress, downsample, and linearize PDFs via Ghostscript/qpdf. |
| `PDF/Security` | Encrypt, decrypt, password-protect, and set permissions on PDFs. |
| `PDF/Convert` | Convert PDFs to/from images, text, and other document formats. |
| `PDF/OCR` | Add a searchable text layer to scanned PDFs. |
| `Docs/Convert` | Cross-format document conversion via Pandoc and friends (Markdown/HTML/DOCX/EPUB). |
| `Docs/Templating` | Generate documents from templates and data (token-fill, JSON/CSV-driven docgen). |
| `Docs/MailMerge` | App-agnostic mail-merge / batch document generation from a data source. |

### Email, Calendar & Communication

Tools that automate email, calendars, contacts, and team-chat/meeting platforms — from Outlook/Exchange and Gmail to Slack, Teams, and Zoom — plus the cross-cutting workflows of mailbox migration, bulk send, signatures, and rules.

| Category | What belongs here |
|---|---|
| `MSOffice/Outlook/Mail` | Outlook COM/MAPI automation for composing, sending, reading, moving, and exporting mail items. |
| `MSOffice/Outlook/Calendar` | Outlook appointment and meeting automation — create, update, scan, and export calendar items. |
| `MSOffice/Outlook/Contacts` | Outlook contact-folder automation — import/export, dedupe, and bulk-edit address-book entries. |
| `MSOffice/Outlook/Rules` | Outlook server- and client-side rules: create, export, import, and audit mail-handling filters. |
| `MSOffice/Outlook/Signatures` | Outlook signature management — deploy, swap, and bulk-update HTML/RTF/TXT signature sets. |
| `MSOffice/Outlook/Categories` | Outlook color-category and flag automation across mailboxes and item types. |
| `MSOffice/Outlook/Search` | Programmatic mailbox search, filtering, and reporting (DASL/Restrict queries, item counts). |
| `MSOffice/Outlook/PST` | Outlook PST/OST file operations — create, attach, export-to, and split/merge personal stores. |
| `MSOffice/Outlook/Migration` | Mailbox/PST migration and bulk transfer between stores, profiles, or Outlook and other clients. |
| `MSOffice/Exchange/Mailboxes` | Exchange / Microsoft 365 mailbox administration via EXO PowerShell — provisioning, permissions, quotas. |
| `MSOffice/Exchange/Rules` | Exchange transport rules and mail-flow connectors — create, export, and audit org-level mail policy. |
| `MSOffice/Exchange/Reports` | Exchange Online message-trace, audit-log, and usage reporting exports. |
| `MSOffice/Graph/Mail` | Microsoft Graph API mail operations for cloud mailboxes (REST, no Outlook client required). |
| `MSOffice/Graph/Calendar` | Microsoft Graph calendar/event automation against Microsoft 365 without a desktop client. |
| `Email/Gmail` | Gmail / Google Workspace automation via Gmail API or OAuth — send, label, archive, export. |
| `Email/GoogleCalendar` | Google Calendar API automation — create/update events, share calendars, export to ICS. |
| `Email/IMAP` | Generic IMAP client tooling — fetch, search, move, flag, and back up mail on any IMAP server. |
| `Email/SMTP` | Generic SMTP send and bulk-mail tooling against any provider (relay, transactional, mailing-list). |
| `Email/Migration` | Cross-provider mailbox migration and sync (IMAP↔IMAP, Gmail↔M365, PST↔mbox) above any one vendor. |
| `Email/Formats` | Mail-format conversion and inspection — EML/MSG/MBOX/PST/vCard/ICS parsing and transcoding. |
| `Email/BulkSend` | Mail-merge and bulk campaign send across providers — templated, list-driven outbound mail. |
| `Email/Cleanup` | Inbox hygiene and bulk maintenance — dedupe, archive, purge, and unsubscribe automation. |
| `Calendar/Scheduling` | Cross-platform scheduling, free/busy lookup, and meeting-time suggestion tools. |
| `Calendar/Sync` | Two-way calendar sync and ICS feed management between Outlook, Google, and CalDAV sources. |
| `Chat/Slack` | Slack workspace automation via API/webhooks — post messages, manage channels, export history. |
| `Chat/Teams` | Microsoft Teams automation via Graph/webhooks — post to channels, manage teams, export chats. |
| `Chat/Discord` | Discord bot/webhook automation — send messages, manage roles and channels, export logs. |
| `Chat/Webhooks` | Generic incoming-webhook notifiers that fan a message out to one or more chat platforms. |
| `Meetings/Zoom` | Zoom API automation — schedule meetings/webinars, manage users, pull recordings and reports. |
| `Meetings/Teams` | Microsoft Teams online-meeting automation via Graph — create meetings, fetch join links and attendance. |
| `Meetings/Webex` | Cisco Webex meeting automation — schedule, manage, and report on Webex sessions and recordings. |
| `Contacts/Sync` | Cross-platform contact sync and dedupe across Outlook, Google, vCard, and CSV sources. |

### Creative & Design (Adobe et al.)

Categories for automating creative and design applications (Adobe, Affinity, Corel, and open-source/web tools) plus cross-app asset, image, PDF, color, and font workflows that a design power user would script.

| Category | What belongs here |
|---|---|
| `Adobe/Photoshop/Batch` | Batch raster edits driven via Photoshop actions/scripting (resize, crop, watermark, format convert across many files). |
| `Adobe/Photoshop/Layers` | Layer, mask, and smart-object manipulation inside a PSD (rename, flatten, toggle, export-by-layer). |
| `Adobe/Photoshop/Export` | Generate web/app deliverables from PSDs (slices, generators, sprite sheets, asset presets). |
| `Adobe/Illustrator/Artboards` | Artboard creation, arrangement, and per-artboard export in Illustrator. |
| `Adobe/Illustrator/Export` | Vector export and rasterization from AI files (SVG, EPS, PDF, multi-resolution PNG). |
| `Adobe/Illustrator/Vector` | Path/shape cleanup and vector operations (simplify paths, expand strokes, recolor artwork). |
| `Adobe/InDesign/Layout` | Document and page layout automation (master pages, text frames, data-merge, pagination). |
| `Adobe/InDesign/Export` | Output InDesign documents to print/interactive formats (PDF/X, packaged assets, IDML, EPUB). |
| `Adobe/Acrobat/Forms` | PDF form field creation, fill, flatten, and data extraction via Acrobat Pro. |
| `Adobe/Acrobat/Documents` | PDF assembly and transformation in Acrobat (merge, split, OCR, redact, optimize, watermark). |
| `Adobe/Premiere/Export` | Render/export sequences and manage presets in Premiere Pro (and Media Encoder hand-off). |
| `Adobe/AfterEffects/Render` | Composition rendering, render-queue automation, and expression/script helpers in After Effects. |
| `Adobe/Lightroom/Catalog` | Catalog, metadata, keyword, and develop-preset operations in Lightroom Classic. |
| `Adobe/Bridge/Assets` | Asset browsing, metadata batch-edit, and renaming across files via Adobe Bridge. |
| `Affinity/Photo/Export` | Raster export and macro-driven batch jobs in Affinity Photo. |
| `Affinity/Designer/Export` | Vector artboard and asset export from Affinity Designer. |
| `Affinity/Publisher/Export` | Print/PDF and packaged output from Affinity Publisher layouts. |
| `Corel/CorelDRAW/Export` | CorelDRAW macro automation for export, print, and document operations. |
| `GIMP/Scripts` | Headless GIMP batch processing via Script-Fu/Python-Fu (filters, resize, format convert). |
| `Inkscape/Export` | Inkscape CLI for SVG-to-raster/PDF conversion, query, and path operations. |
| `Figma/Assets` | Figma REST/plugin automation for exporting frames, components, and design tokens. |
| `Canva/Export` | Canva API-driven design export and brand-asset retrieval. |
| `Media/Images` | Cross-app raster batch processing with general-purpose tools (resize, crop, optimize, convert). |
| `Media/Vector` | App-agnostic SVG/vector tooling (optimize, minify, sprite, convert). |
| `Media/PDF` | General-purpose PDF processing outside a specific suite (merge, split, compress, OCR). |
| `Design/Color` | Color management and palette workflows (ICC profiles, palette extraction, color-space convert). |
| `Design/Fonts` | Font asset management and conversion (subset, webfont generate, install/inspect, glyph audit). |
| `Design/Assets` | Cross-tool export/delivery pipelines (asset packaging, naming conventions, manifest generation). |
| `Design/Metadata` | Image/document metadata workflows (EXIF/IPTC/XMP read, write, scrub) across formats. |

### 3D, Animation, VFX & Rendering

Categories for automating 3D content-creation suites, renderers, and the interchange/asset pipelines (geometry, UV, texture, mocap) that move data between them.

| Category | What belongs here |
|---|---|
| `Blender/Render` | Headless/CLI render jobs, frame ranges, render-engine switches, and output settings driven through Blender. |
| `Blender/Scene` | Scene assembly, collection/object management, scripting via bpy, and .blend file housekeeping. |
| `Blender/Export` | Mesh/scene export out of Blender to interchange formats. |
| `Blender/Geometry` | Modeling, modifier, retopo, and UV operations performed inside Blender. |
| `Maya/Render` | Autodesk Maya batch rendering and render-layer/AOV setup via Render.exe and MEL/Python. |
| `Maya/Scene` | Maya scene scripting, reference management, and .ma/.mb file operations. |
| `Maya/Rigging` | Skeleton, skinning, and rig automation in Maya. |
| `Maya/Export` | Exporting geometry, caches, and scenes from Maya to interchange formats. |
| `3dsMax/Render` | Autodesk 3ds Max command-line/network rendering and render-setup automation. |
| `3dsMax/Scene` | 3ds Max scene scripting via MAXScript/Python and .max file batch operations. |
| `3dsMax/Export` | Exporting meshes and scenes from 3ds Max to interchange formats. |
| `Cinema4D/Render` | Maxon Cinema 4D command-line rendering and take/render-setting automation. |
| `Cinema4D/Scene` | Cinema 4D scene scripting and .c4d project operations. |
| `Houdini/Render` | SideFX Houdini ROP/Karma rendering and render-output cook automation. |
| `Houdini/Simulation` | Headless simulation cooks (FLIP, Pyro, Vellum, RBD) and cache generation via hbatch. |
| `Houdini/Geometry` | Procedural geometry processing, HDA cooks, and geo caching in Houdini. |
| `Houdini/Export` | Exporting geometry and scenes from Houdini to interchange formats. |
| `ZBrush/Sculpt` | Pixologic ZBrush sculpting, subtool, and ZScript/decimation automation. |
| `ZBrush/Export` | Exporting high/low-res meshes and maps out of ZBrush. |
| `SketchUp/Model` | Trimble SketchUp model scripting and .skp operations via the Ruby API. |
| `SketchUp/Export` | Exporting SketchUp models to interchange and CAD formats. |
| `Render/Arnold` | Standalone Arnold rendering of .ass scenes and Arnold-specific render config. |
| `Render/VRay` | Standalone V-Ray rendering of .vrscene files and V-Ray distributed/render config. |
| `Render/Redshift` | Redshift command-line rendering and proxy generation. |
| `Render/KeyShot` | Luxion KeyShot headless rendering and scene/queue automation. |
| `Render/RenderManager` | Render-farm submission, job management, and queue control across engines. |
| `Render/Compositing` | Post-render compositing and EXR/frame-sequence processing. |
| `Pipeline/USD` | Pixar USD authoring, composition, and stage inspection/conversion tooling. |
| `Pipeline/Convert` | Cross-format mesh/scene conversion between FBX, OBJ, glTF, Alembic, USD, etc. |
| `Pipeline/Alembic` | Alembic cache inspection, conversion, and stitching for geometry/animation interchange. |
| `Pipeline/AssetManagement` | Asset library organization, dependency relinking, and version tracking across DCC tools. |
| `Texturing/Baking` | Baking texture maps (normal, AO, curvature) from high to low-poly meshes. |
| `Texturing/PBR` | PBR material authoring, texture set export, and channel packing. |
| `Texturing/UV` | Standalone UV unwrapping, packing, and layout automation. |
| `Texturing/Optimize` | Texture resizing, format conversion, and compression for delivery. |
| `Geometry/Retopo` | Automatic retopology and mesh re-meshing outside a specific DCC. |
| `Geometry/Optimize` | Mesh decimation, LOD generation, and polygon reduction. |
| `Geometry/Scan` | Photogrammetry and 3D-scan cleanup, alignment, and mesh-from-scan generation. |
| `Animation/Mocap` | Motion-capture retargeting, cleanup, and BVH/FBX animation processing. |

### Game Development

Tools that drive game engines (Unity, Unreal, Godot, GameMaker, Defold) and the cross-engine asset, build, packaging, and content pipelines a game-dev power user automates.

| Category | What belongs here |
|---|---|
| `Unity/Assets/Import` | Batch-import and reimport of art/audio/data assets into a Unity project, with importer settings. |
| `Unity/Assets/Addressables` | Build, analyze, and manage Unity Addressables groups, catalogs, and content updates. |
| `Unity/Assets/Bundles` | AssetBundle building, manifest inspection, and dependency analysis. |
| `Unity/Scenes/Export` | Scene/prefab export, baking, and lightmap/navmesh generation automation. |
| `Unity/Build/Player` | Headless player builds via BuildPipeline for each target platform and configuration. |
| `Unity/Build/Packages` | UPM package management, manifest edits, and registry operations. |
| `Unreal/Assets/Import` | Import meshes, textures, and audio into an Unreal project through the editor/automation. |
| `Unreal/Cook/Content` | Cook content for target platforms and inspect cook output. |
| `Unreal/Build/Package` | Build and stage/package shipping builds via UnrealBuildTool and the Automation Tool. |
| `Unreal/Blueprints/Tools` | Blueprint asset audits, nativization checks, and editor-utility automation. |
| `Godot/Export/Templates` | Headless Godot exports per platform using export presets and templates. |
| `Godot/Assets/Import` | Reimport and manage Godot resource imports (.import) and asset reformatting. |
| `Godot/Build/Project` | Godot project packaging, PCK/ZIP packing, and headless build automation. |
| `GameMaker/Build/Export` | GameMaker Studio runtime builds and platform exports via Igor/CLI. |
| `GameMaker/Assets/Sprites` | Sprite and resource import/management for GameMaker projects. |
| `Defold/Build/Bundle` | Defold bob.jar headless builds and platform bundling. |
| `Defold/Assets/Atlas` | Defold atlas/tilesource generation and resource management. |
| `Art/SpriteAtlas` | Engine-agnostic sprite-sheet and texture-atlas packing with trim/padding. |
| `Art/TextureCompress` | GPU texture compression and format conversion (BCn, ASTC, ETC, KTX/Basis). |
| `Art/ModelConvert` | 3D model format conversion and optimization (glTF, FBX, OBJ) for engine ingest. |
| `Art/Shaders` | Shader compilation, cross-compilation, and reflection across HLSL/GLSL/SPIR-V. |
| `Audio/Convert` | Game audio transcoding and loudness/normalization for engine import. |
| `Audio/Middleware` | Audio middleware bank/soundbank building and integration (Wwise, FMOD). |
| `Pipeline/Localization` | Extract, merge, and import localization strings and language packs across engines. |
| `Pipeline/Build` | Cross-engine build orchestration, CI triggers, and version stamping. |
| `Pipeline/Packaging` | Platform/store packaging and signing for distribution targets. |
| `Pipeline/Publishing` | Upload and deploy builds to storefronts and distribution channels. |
| `Pipeline/Levels` | Level/scene/tilemap export and conversion between authoring tools and engines. |
| `Pipeline/Data` | Game data table and config conversion/validation (CSV/JSON/ScriptableObject/DataTable). |
| `Pipeline/Assets` | Cross-engine asset auditing, dedup, and reference-integrity checks. |

### Audio, Video & Image Media

Tools that automate audio, video, and image media work — transcoding, muxing, subtitles, audio editing/mastering, image batch processing, metadata, and screen capture — spanning both commercial apps and general-purpose media utilities.

| Category | What belongs here |
|---|---|
| `Media/ffmpeg` | FFmpeg-driven transcode/mux/filter pipelines — the existing shipped cell; keep and extend here for general FFmpeg jobs. |
| `Media/Video/Transcode` | General video format/codec conversion and re-encoding (non-app-specific, multi-tool). |
| `Media/Video/Mux` | Container muxing/remuxing, track add/remove/reorder, chapter editing. |
| `Media/Video/Subtitles` | Subtitle extraction, conversion, OCR, sync, and hard/soft-sub burn-in. |
| `Media/Video/Edit` | Cut/trim/concat/crop/resize and lossless segment operations on video. |
| `Media/Video/Stream` | Live capture, RTMP/HLS streaming, and screencast/scene automation. |
| `Media/Video/Analyze` | Probe/inspect streams — codec, bitrate, frame, and quality (VMAF/PSNR) metrics. |
| `Media/Audio/Transcode` | Audio format conversion, resampling, channel remap, and bitrate changes. |
| `Media/Audio/Edit` | Trim/concat/mix/fade and batch audio processing. |
| `Media/Audio/Master` | Loudness normalization, EBU R128/ReplayGain, dynamics and waveform analysis. |
| `Media/Audio/Tags` | Audio metadata/tagging and cover-art embedding. |
| `Media/Audio/Reaper` | REAPER DAW project/render automation via ReaScript. |
| `Media/Audio/Audacity` | Audacity batch macros and mod-script-pipe automation. |
| `Media/Image/Convert` | Batch image format conversion across raster types. |
| `Media/Image/Resize` | Batch resize/crop/thumbnail and aspect/fit operations. |
| `Media/Image/Optimize` | Lossless/lossy compression and stripping to shrink image files. |
| `Media/Image/Watermark` | Overlay text/logo watermarks and stamps across image batches. |
| `Media/Image/Composite` | Montage, collage, tiling, and layer compositing of images. |
| `Media/Image/Exif` | EXIF/IPTC/XMP metadata read, edit, strip, and rename-by-metadata. |
| `Media/Capture/Screenshot` | Still screen/window capture to image files. |
| `Media/Capture/Record` | Screen recording to video, including region/window/cursor capture. |
| `Media/Capture/Gif` | Animated GIF/APNG creation and palette optimization from clips. |
| `Adobe/Photoshop/Batch` | Batch raster edits driven via Photoshop actions/scripting (resize, crop, watermark, format convert across many files). |
| `Adobe/Premiere/Render` | Adobe Premiere Pro project export/render automation. |
| `Adobe/AfterEffects/Render` | Composition rendering, render-queue automation, and expression/script helpers in After Effects. |
| `Adobe/Lightroom/Export` | Lightroom catalog export/develop preset automation. |
| `Media/Image/Gimp` | GIMP batch image processing via Script-Fu/Python-Fu headless mode. |

### Software Development (DevTools)

Tooling that automates the software-development lifecycle — version control, building, dependency management, code quality, testing, debugging, code generation, and developer-utility workflows.

| Category | What belongs here |
|---|---|
| `DevTools/Git` | Local Git version-control operations: staging, committing, branching, stashing, history, blame, bisect. |
| `DevTools/Git/Hooks` | Git hook installation, management, and pre-commit automation harnesses. |
| `DevTools/Git/Submodules` | Submodule, subtree, and multi-repo vendoring/sync operations. |
| `GitHub/Repos` | GitHub-hosted repo automation via the gh CLI/API: clone, fork, release, repo settings. |
| `GitHub/PullRequests` | GitHub PR lifecycle: create, review, merge, check status, manage labels. |
| `GitHub/Actions` | GitHub Actions CI workflows: trigger, watch runs, manage secrets and workflow files. |
| `DevTools/VCS` | Non-Git version control and cross-VCS bridges (Mercurial, SVN, Perforce, Jujutsu). |
| `DevTools/Diff` | Standalone diff, merge, and patch tools independent of any single VCS. |
| `DevTools/Build` | General-purpose build orchestration and task runners not tied to one language ecosystem. |
| `DevTools/Build/Java` | JVM build systems and lifecycle tasks (compile, package, publish). |
| `DevTools/Build/DotNet` | .NET / MSBuild build, restore, publish, and solution operations. |
| `DevTools/Build/Native` | C/C++/native toolchain compilation, linking, and cross-compile drivers. |
| `DevTools/Packages/Node` | JavaScript/TypeScript package management: install, audit, publish, scripts. |
| `DevTools/Packages/Python` | Python dependency and environment management: install, lock, virtualenv, build. |
| `DevTools/Packages/Rust` | Rust/Cargo crate management, build, and publish. |
| `DevTools/Packages/DotNet` | NuGet package restore, add, pack, and feed management. |
| `DevTools/Packages/PHP` | PHP/Composer dependency install, update, and autoload operations. |
| `DevTools/Lint` | Linters and static-analysis runners that flag code issues without rewriting. |
| `DevTools/Format` | Opinionated code formatters that rewrite source to a canonical style. |
| `DevTools/Test` | Test-suite runners: discover, run, filter, and report unit/integration tests. |
| `DevTools/Test/Coverage` | Code-coverage measurement and report generation. |
| `DevTools/Test/E2E` | Browser/end-to-end and acceptance test drivers. |
| `DevTools/Debug` | Interactive debuggers and crash/core inspection front-ends. |
| `DevTools/Profiling` | Performance, CPU, memory, and flamegraph profilers. |
| `DevTools/Codegen` | Scaffolding, project bootstrap, and code/template generators. |
| `DevTools/Regex` | Regular-expression building, testing, and explanation utilities. |
| `DevTools/API` | HTTP/API and SDK helpers: request clients, schema tooling, mock servers. |
| `DevTools/Docs` | API/reference documentation generation and site building. |
| `DevTools/Search` | Code search, indexing, and symbol/cross-reference navigation across a tree. |
| `DevTools/Containers` | Container image build/run and local dev-container orchestration. |
| `DevTools/SecScan` | Dependency vulnerability, secret, and SAST security scanners run in the dev loop. |
| `DevTools/DB` | Schema migration, query, and database client utilities used during development. |
| `VisualStudio/Solutions` | Visual Studio / VS solution and project automation driven through devenv or its CLI. |
| `JetBrains/IDE` | JetBrains IDE automation: open projects, run inspections, apply code style via the CLI. |
| `VSCode/Workspace` | VS Code workspace, extension, and command automation via the code CLI. |

### DevOps, Cloud & Infrastructure

Tools that build, ship, provision, and operate cloud infrastructure and containerized workloads — IaC, container orchestration, the major cloud CLIs, CI/CD pipelines, secrets, and observability.

| Category | What belongs here |
|---|---|
| `DevOps/Docker` | Local Docker engine operations — images, containers, volumes, networks, builds, and cleanup. |
| `DevOps/Compose` | Multi-container app definition and lifecycle via Docker Compose stacks. |
| `DevOps/Buildx` | Multi-platform / multi-arch image builds and build caching with BuildKit. |
| `DevOps/Registry` | Container registry push/pull, tagging, signing, and scanning across registries. |
| `DevOps/Kubernetes` | Cluster operations against the Kubernetes API — apply, get, logs, exec, contexts. |
| `DevOps/Helm` | Helm chart packaging, templating, install/upgrade, and repo management. |
| `DevOps/Kustomize` | Kubernetes manifest overlay/patch builds without templating. |
| `DevOps/GitOps` | Declarative continuous-delivery sync of cluster state from Git repos. |
| `DevOps/Terraform` | Terraform / OpenTofu IaC — init, plan, apply, state, and module workflows. |
| `DevOps/Pulumi` | Imperative IaC in general-purpose languages — stacks, preview, up. |
| `DevOps/Ansible` | Agentless configuration management and provisioning via playbooks/inventories. |
| `DevOps/Packer` | Machine- and container-image building from a single source template. |
| `DevOps/Vagrant` | Reproducible local dev VMs and box lifecycle management. |
| `DevOps/Secrets` | Secret storage, retrieval, rotation, and injection into pipelines/runtime. |
| `DevOps/CICD` | Pipeline definition, triggering, and run inspection for CI/CD systems. |
| `DevOps/Observability` | Metrics, logs, traces, and dashboard tooling for running systems. |
| `DevOps/Policy` | Policy-as-code linting and admission checks for IaC and manifests. |
| `AWS/IAM` | AWS identity, roles, policies, and credential/SSO management. |
| `AWS/EC2` | AWS compute — instances, AMIs, security groups, key pairs, autoscaling. |
| `AWS/S3` | AWS object storage — buckets, sync, lifecycle, presigned URLs. |
| `AWS/Lambda` | AWS serverless functions — deploy, invoke, logs, and layers. |
| `AWS/EKS` | AWS managed Kubernetes cluster provisioning and kubeconfig wiring. |
| `AWS/CloudFormation` | AWS-native IaC — stack create/update, change sets, and CDK synth. |
| `Azure/Identity` | Azure AD / Entra sign-in, service principals, and RBAC role assignment. |
| `Azure/Compute` | Azure VMs, scale sets, and disk/image management. |
| `Azure/AKS` | Azure managed Kubernetes provisioning and credential retrieval. |
| `Azure/Storage` | Azure blob/file storage accounts, containers, and data transfer. |
| `GCP/IAM` | Google Cloud auth, service accounts, and IAM policy bindings. |
| `GCP/Compute` | GCE instances, images, and instance-group management. |
| `GCP/GKE` | Google managed Kubernetes cluster ops and kubeconfig credentials. |
| `GCP/Storage` | Google Cloud Storage buckets, sync, and object lifecycle. |
| `DevOps/Networking` | Service mesh, ingress, DNS, and connectivity tooling for infra. |
| `DevOps/Cost` | Cloud cost estimation and FinOps reporting for IaC and accounts. |

### Data, Databases & Analytics

Tools that connect to, query, move, transform, model, back up, and analyze data across relational and NoSQL databases, warehouses, file-based datasets, and BI platforms.

| Category | What belongs here |
|---|---|
| `Data/SQL` | General, engine-agnostic SQL execution and ad-hoc query running against any relational source. |
| `Data/Query` | Query files run against local datasets (CSV/JSON/Parquet) via embedded SQL engines, no server needed. |
| `Data/ETL` | Pipeline and data-movement jobs that extract, transform, and load between sources. |
| `Data/Transform` | In-place data wrangling, cleaning, reshaping, and column ops on tabular/structured files. |
| `Data/Formats` | Convert and inspect data file formats (CSV, JSON, Parquet, Avro, XML, NDJSON). |
| `Data/Validation` | Schema validation, data-quality checks, and profiling of datasets. |
| `Data/Science` | Data-science / analytics scripting, notebooks, and statistical computation over datasets. |
| `Data/Migration` | Cross-engine schema/data migration and database version-management workflows. |
| `Data/Backup` | Engine-agnostic backup, dump, and restore orchestration for databases. |
| `PostgreSQL/Query` | Run SQL and interactive sessions against PostgreSQL servers. |
| `PostgreSQL/Admin` | PostgreSQL server/role/extension administration and maintenance tasks. |
| `PostgreSQL/Backup` | PostgreSQL dump, restore, and point-in-time backup operations. |
| `PostgreSQL/Schema` | PostgreSQL schema inspection, diffing, and migration generation. |
| `MySQL/Query` | Run SQL and interactive sessions against MySQL/MariaDB servers. |
| `MySQL/Admin` | MySQL/MariaDB administration, tuning, and maintenance. |
| `MySQL/Backup` | MySQL/MariaDB logical and physical backup and restore. |
| `SQLServer/Query` | Run T-SQL and interactive sessions against Microsoft SQL Server. |
| `SQLServer/Admin` | SQL Server instance, database, and maintenance administration. |
| `SQLServer/Backup` | SQL Server backup, restore, and BACPAC/DACPAC operations. |
| `Oracle/Query` | Run SQL/PL-SQL against Oracle Database instances. |
| `Oracle/DataPump` | Oracle export/import, Data Pump, and bulk-load utilities. |
| `SQLite/Tools` | Create, query, inspect, and maintain SQLite database files. |
| `MongoDB/Shell` | Query and script against MongoDB collections. |
| `MongoDB/Backup` | MongoDB dump, restore, and BSON/JSON import-export. |
| `Redis/Tools` | Interact with, inspect, and manage Redis key-value stores. |
| `Elasticsearch/Search` | Query, index, and manage Elasticsearch/OpenSearch clusters. |
| `Snowflake/Warehouse` | Query, load, and manage Snowflake warehouses and objects. |
| `BigQuery/Warehouse` | Run queries and manage datasets/tables in Google BigQuery. |
| `Redshift/Warehouse` | Query and administer Amazon Redshift clusters and data. |
| `Databricks/Lakehouse` | Run SQL and manage jobs/clusters on the Databricks lakehouse. |
| `PowerBI/Reports` | Publish, refresh, and manage Microsoft Power BI datasets and reports. |
| `Tableau/Reports` | Publish, refresh, and manage Tableau workbooks and data sources. |
| `Looker/Reports` | Manage LookML, run looks, and administer Looker/Looker Studio. |

### AI, ML & LLM Tooling

Tools that build, run, and operate AI/ML systems — model training and inference, LLM workflows (prompting, embeddings, RAG, fine-tuning), local-model runtimes, dataset/labeling pipelines, vision/OCR, speech, and cloud AI-provider API clients.

| Category | What belongs here |
|---|---|
| `AI/Training` | Drive model training/fine-tuning runs, checkpoints, and hyperparameter sweeps for classic ML and deep learning. |
| `AI/Training/Distributed` | Launch and coordinate multi-GPU / multi-node training jobs and accelerators. |
| `AI/Training/Sweeps` | Hyperparameter search, experiment sweeps, and run orchestration. |
| `AI/Experiments` | Track, log, and compare experiment runs, metrics, and artifacts. |
| `AI/Inference` | Run trained models for prediction/serving, batch or interactive. |
| `AI/Inference/Optimize` | Quantize, prune, distill, and compile models for faster/smaller inference. |
| `AI/Models` | Convert, export, inspect, and validate model files across formats. |
| `AI/Models/Registry` | Pull, push, and manage model artifacts from hubs and registries. |
| `AI/Datasets` | Build, clean, split, and convert datasets for training and evaluation. |
| `AI/Datasets/Labeling` | Annotation, labeling, and synthetic-data generation pipelines. |
| `AI/Datasets/Version` | Version, snapshot, and track large data/model artifacts. |
| `AI/Evaluation` | Benchmark and evaluate model quality, accuracy, and regressions. |
| `AI/LLM/Prompting` | Author, template, and version prompts; run prompt chains and one-off completions. |
| `AI/LLM/Agents` | Build and run autonomous/agentic LLM workflows and tool-using agents. |
| `AI/LLM/RAG` | Retrieval-augmented generation pipelines: ingest, chunk, retrieve, and answer. |
| `AI/LLM/Embeddings` | Generate, store, and query text/image embeddings. |
| `AI/LLM/VectorDB` | Create, index, and query vector databases backing RAG and semantic search. |
| `AI/LLM/FineTune` | Fine-tune and adapter-train LLMs (LoRA/QLoRA, instruction tuning). |
| `AI/LLM/Guardrails` | Validate, constrain, and structure LLM outputs; safety and schema enforcement. |
| `AI/Local/Ollama` | Manage and run local models through the Ollama runtime. |
| `AI/Local/LlamaCpp` | Run, quantize, and serve GGUF models with llama.cpp tooling. |
| `AI/Local/Runtimes` | Other local/self-hosted inference runtimes and model launchers. |
| `AI/Vision` | Computer-vision inference: detection, segmentation, classification, image embeddings. |
| `AI/Vision/OCR` | Optical character recognition and document/image-to-text extraction. |
| `AI/Speech/STT` | Speech-to-text transcription and audio-to-text pipelines. |
| `AI/Speech/TTS` | Text-to-speech and voice synthesis. |
| `AI/API/OpenAI` | Call OpenAI APIs for chat, completions, embeddings, images, and audio. |
| `AI/API/Anthropic` | Call Anthropic Claude APIs for messages, tools, and batch. |
| `AI/API/HuggingFace` | Hugging Face Hub and Inference API/Endpoints clients. |
| `AI/API/Gateway` | Multi-provider routing, proxies, and unified LLM API gateways. |
| `AI/Serving` | Wrap models as deployable HTTP/gRPC services and pipelines. |
| `AI/Observability` | Trace, monitor, and debug LLM/agent calls — cost, latency, token usage. |

### System & OS Administration

Tools that automate operating-system and machine administration — Windows/Linux/macOS system internals, file and folder operations, process and service control, users and permissions, software install/update, and infrastructure-config tooling.

| Category | What belongs here |
|---|---|
| `System/Registry` | Read, edit, export, import, and back up the Windows registry. |
| `System/Services` | Create, start/stop, configure, and audit Windows services and daemons. |
| `System/ScheduledTasks` | Create and manage Windows Task Scheduler jobs and cron schedules. |
| `System/EventLogs` | Query, filter, export, and clear Windows event logs and syslog. |
| `System/WMI` | Query and invoke WMI/CIM classes for system inventory and control. |
| `System/Startup` | Manage boot, startup programs, and autoruns entries. |
| `System/Performance` | Capture and analyze CPU, memory, disk, and counter performance data. |
| `System/Processes` | List, inspect, prioritize, and kill processes and memory usage. |
| `System/Drivers` | Enumerate, install, roll back, and sign device drivers. |
| `System/Hardware` | Inventory and diagnose hardware, BIOS/UEFI, and device manager state. |
| `System/PowerShell` | PowerShell scripting, DSC config, modules, and execution-policy tooling. |
| `System/GroupPolicy` | Edit, apply, model, and report Group Policy objects. |
| `System/Network` | Configure adapters, IP/DNS, firewall rules, and routing at the OS level. |
| `System/Updates` | Manage OS patches, Windows Update, and update history. |
| `System/Power` | Manage power plans, sleep/hibernate, and wake settings. |
| `System/Cleanup` | Disk cleanup, temp-file purge, and component-store servicing. |
| `Files/Rename` | Bulk and pattern-based file/folder renaming. |
| `Files/Dedupe` | Find and remove duplicate files by hash or content. |
| `Files/Sync` | Mirror, sync, and replicate folders locally or to remote targets. |
| `Files/Search` | Fast index-based file and content search. |
| `Files/Compression` | Create and extract archives; compress/decompress files. |
| `Files/Permissions` | View and modify file/folder ACLs, ownership, and attributes. |
| `Files/Hashing` | Compute and verify file checksums and integrity. |
| `Files/Metadata` | Read and edit file metadata, timestamps, and EXIF. |
| `Storage/Disk` | Partition, format, and manage disks and volumes. |
| `Storage/Backup` | Image-level and file-level backup and restore. |
| `Storage/Filesystem` | Check, repair, and tune filesystems and disk health. |
| `Users/Accounts` | Create, modify, and disable local and domain user accounts. |
| `Users/Groups` | Manage local and directory groups and memberships. |
| `Users/ActiveDirectory` | Query and administer Active Directory objects, OUs, and policies. |
| `Software/Install` | Install, repair, and uninstall applications via package managers and MSI. |
| `Software/PackageManager` | Manage Linux/macOS package repositories and installed packages. |
| `Software/Inventory` | Audit installed software, licenses, and versions. |
| `Linux/Admin` | General Linux system administration and shell tooling. |
| `macOS/Admin` | macOS system administration and management tooling. |
| `Sysinternals/Tools` | Microsoft Sysinternals utilities for deep Windows diagnostics. |

### Networking & Internet

Command-line and scriptable tools for diagnosing networks, querying DNS, talking to HTTP/REST APIs, transferring and downloading files, capturing packets, and managing proxies/VPN/tunnels.

| Category | What belongs here |
|---|---|
| `Network/Diagnostics` | Basic reachability and latency probes — is the host up and how far away. |
| `Network/Scanning` | Host discovery, port scanning, and service/version fingerprinting of a network range. |
| `Network/Ports` | Connection state and socket inspection — who's listening, what's connected. |
| `Network/Bandwidth` | Throughput and performance benchmarking between two endpoints. |
| `Network/Traffic` | Live per-interface / per-connection traffic monitoring and bandwidth accounting. |
| `Network/Routing` | Inspect and manipulate routing tables, interfaces, and addresses. |
| `Network/Wireless` | Wi-Fi scanning, association, and link diagnostics. |
| `Network/DNS` | Name-resolution queries, record lookups, and DNS server diagnostics. |
| `Network/SNMP` | SNMP polling, walking, and trap handling for managed devices. |
| `Network/Capture` | Packet capture and protocol-level inspection of wire traffic. |
| `Network/Tunneling` | Port-forwarding and exposing local services through tunnels. |
| `Network/Proxy` | Local/forward/reverse proxy launchers and SOCKS relays. |
| `Network/VPN` | VPN tunnel setup, connection, and status control. |
| `Network/SSH` | Remote shell sessions, key management, and config-driven connections. |
| `Web/HTTP` | General HTTP request senders for fetching URLs and probing endpoints. |
| `Web/API` | REST/GraphQL client workflows — build, send, and inspect API calls and collections. |
| `Web/JSON` | Parse, filter, and reshape JSON API responses on the command line. |
| `Web/Auth` | Token, JWT, and OAuth helpers for authenticating API requests. |
| `Web/Download` | Bulk and resumable file downloads / mirroring from the web. |
| `Web/Media` | Download audio/video and metadata from streaming sites. |
| `Web/Scraping` | Extract structured data from HTML pages and crawl sites. |
| `Web/Automation` | Headless-browser scripting for JS-rendered pages and UI flows. |
| `Web/Recon` | Web/asset reconnaissance — subdomain enumeration, endpoint discovery, fuzzing. |
| `Web/TLS` | Certificate inspection, TLS handshake testing, and SSL config auditing. |
| `Transfer/FTP` | Classic FTP/FTPS file transfer sessions and scripted uploads. |
| `Transfer/SFTP` | SSH-based secure file copy and transfer. |
| `Transfer/WebDAV` | WebDAV mounts and transfers against remote shares. |
| `Transfer/Cloud` | Sync and transfer to object-storage / cloud endpoints over the network. |

### Security, Cryptography & Forensics

Tools that encrypt, sign, hash, scan, harden, and investigate — covering cryptography and PKI, secrets management, vulnerability scanning and authorized pentest, malware analysis, digital forensics, and compliance auditing.

| Category | What belongs here |
|---|---|
| `Security/Crypto/Encrypt` | Symmetric/asymmetric file and stream encryption/decryption. |
| `Security/Crypto/Hash` | Compute and verify cryptographic hashes and checksums. |
| `Security/Crypto/Sign` | Digital signing and signature verification of files and messages. |
| `Security/Crypto/KeyMgmt` | Generate, convert, inspect, and rotate cryptographic keys. |
| `Security/Crypto/Encoding` | Base/hex/PEM/DER encoding and decoding for crypto material. |
| `OpenSSL/Cert/Generate` | Create CSRs, self-signed certs, and key pairs with OpenSSL. |
| `OpenSSL/Cert/Inspect` | Decode and verify X.509 certificates, chains, and CRLs. |
| `OpenSSL/Cert/Convert` | Convert between PEM, DER, PFX/PKCS#12, and JKS formats. |
| `OpenSSL/TLS/Probe` | Test live TLS endpoints, ciphers, and protocol versions. |
| `Security/PKI/CA` | Run and manage certificate authorities and ACME issuance. |
| `Security/Secrets/Vault` | Centralized secret storage, retrieval, and dynamic credentials. |
| `Security/Secrets/Password` | Password manager CLIs, generators, and strength checks. |
| `Security/Secrets/Scan` | Detect leaked credentials, keys, and tokens in code and history. |
| `Security/Recon/Network` | Host discovery, port scanning, and service fingerprinting. |
| `Security/Recon/Domain` | DNS, subdomain, and OSINT enumeration for a target scope. |
| `Security/Recon/Web` | Web content, directory, and tech-stack discovery. |
| `Security/Scan/Vuln` | Authenticated/unauthenticated vulnerability scanning of hosts and apps. |
| `Security/Scan/Container` | Scan images, IaC, and dependencies for known CVEs and misconfig. |
| `Security/Scan/Code` | Static analysis and SAST for security defects in source. |
| `Security/Exploit/Framework` | Authorized exploitation frameworks and payload generation. |
| `Security/Exploit/Password` | Authorized credential cracking and brute-force testing. |
| `Security/Wireless/WiFi` | Authorized Wi-Fi auditing, capture, and handshake cracking. |
| `Security/Malware/Static` | Static triage of binaries — strings, packing, signatures, YARA. |
| `Security/Malware/Sandbox` | Dynamic detonation and behavioral analysis in isolation. |
| `Security/Malware/Reverse` | Disassembly and decompilation for reverse engineering. |
| `Security/Forensics/Disk` | Disk imaging, carving, and filesystem forensic analysis. |
| `Security/Forensics/Memory` | Memory acquisition and RAM forensic analysis. |
| `Security/Forensics/Network` | Packet capture and traffic forensic reconstruction. |
| `Security/Forensics/Artifacts` | Parse OS and application artifacts (logs, registry, browser, email). |
| `Security/Stego/Embed` | Hide and extract data within images, audio, and files. |
| `Security/Antivirus/Scan` | On-demand malware scanning and signature updates. |
| `Security/Compliance/Audit` | Benchmark hosts against CIS/STIG and report compliance gaps. |
| `Security/Compliance/Hardening` | Apply and verify system/config hardening baselines. |

### Documents, Text & Publishing

Tools that convert, typeset, OCR, lint, transform, and publish documents and text — from LaTeX/Pandoc pipelines and e-book packaging to OCR, redaction, citations, and grep/sed-style text processing.

| Category | What belongs here |
|---|---|
| `Docs/Pandoc` | Universal document conversion between markup/office/e-book formats via Pandoc. |
| `Docs/LaTeX` | TeX/LaTeX typesetting, compilation, and PDF build pipelines. |
| `Docs/LaTeX/Bibliography` | BibTeX/BibLaTeX bibliography processing and reference-list generation for TeX. |
| `Docs/Markdown` | Markdown linting, formatting, rendering, and table-of-contents generation. |
| `Docs/AsciiDoc` | AsciiDoc authoring, validation, and rendering to HTML/PDF. |
| `Docs/reStructuredText` | reStructuredText processing and Sphinx-based documentation builds. |
| `Docs/Convert` | Cross-format document conversion via Pandoc and friends (Markdown/HTML/DOCX/EPUB). |
| `Docs/OCR` | Optical character recognition turning scanned images/PDFs into searchable text. |
| `Docs/Citations` | Citation/reference-management and bibliography export across reference managers. |
| `Docs/Templating` | Generate documents from templates and data (token-fill, JSON/CSV-driven docgen). |
| `Docs/Diagrams` | Text-to-diagram rendering embedded in document workflows. |
| `Docs/SpellGrammar` | Spell-checking, grammar, and style/prose linting for documents. |
| `Adobe/Acrobat/PDF` | Acrobat-driven PDF creation, editing, forms, and preflight automation. |
| `PDF/Manipulate` | App-agnostic PDF merge, split, rotate, stamp, and page-level edits. |
| `PDF/Extract` | Pull text, tables, images, and metadata out of PDFs. |
| `PDF/Optimize` | Compress, downsample, and linearize PDFs via Ghostscript/qpdf. |
| `PDF/Security` | Encrypt, decrypt, password-protect, and set permissions on PDFs. |
| `Ebooks/Calibre` | Calibre-driven e-book library management and metadata editing. |
| `Ebooks/Convert` | E-book format conversion between EPUB/MOBI/AZW3/PDF. |
| `Text/Search` | Pattern-based text search across files (grep-style). |
| `Text/Transform` | Stream editing and field-wise text transformation (sed/awk-style). |
| `Text/Encoding` | Character-encoding detection and conversion, line-ending and BOM fixes. |
| `Text/Diff` | Textual diff and merge between files and document revisions. |
| `Text/Format` | Wrapping, reflowing, columnizing, and prettifying plain text. |
| `Docs/Redaction` | Removing or masking sensitive content and stripping document metadata. |
| `Docs/Compare` | Visual/structural comparison of formatted documents (Word/PDF redlines). |
| `Docs/Metadata` | Reading and editing document metadata across formats. |
| `Publish/StaticSite` | Static-site/documentation publishing from Markdown/rST sources. |
| `Publish/Slides` | Generating presentation decks from plain-text/Markdown sources. |

### Science, Math & Research

Tools for statistics, numerical and symbolic math, scientific computing, bioinformatics, chemistry, physics, astronomy, plotting, and lab/instrument data processing — both command-line scientific software and general research workflows.

| Category | What belongs here |
|---|---|
| `Science/Stats/R` | Drive the R statistical environment: run scripts, render R Markdown, fit models, batch analyses. |
| `Science/Stats/Python` | Python statistical/data-analysis runners built on the scientific stack. |
| `Science/Stats/SPSS` | Run IBM SPSS syntax jobs and batch statistical procedures headless. |
| `Science/Stats/SAS` | Execute SAS programs and DATA-step/PROC batch jobs from the CLI. |
| `Science/Stats/JASP` | Bayesian and frequentist analyses via JASP/jamovi batch interfaces. |
| `Science/Stats/Stata` | Run Stata do-files and estimation commands in batch mode. |
| `Science/Math/Numerical` | Numerical computing and linear-algebra/array workflows. |
| `Science/Math/Symbolic` | Computer-algebra systems for symbolic manipulation, solving, and simplification. |
| `Science/Math/Solvers` | Optimization, equation, and constraint solvers; ODE/PDE integration. |
| `Science/Math/Units` | Unit conversion and dimensional-analysis utilities. |
| `Science/Bioinformatics/Sequence` | Sequence alignment, search, and manipulation tools. |
| `Science/Bioinformatics/Genomics` | Variant calling, read mapping, and genomic file processing. |
| `Science/Bioinformatics/Biopython` | Scripted sequence/structure parsing and pipeline glue via Biopython. |
| `Science/Bioinformatics/Phylogenetics` | Phylogenetic tree inference and analysis. |
| `Science/Chemistry/RDKit` | Cheminformatics: molecule parsing, descriptors, fingerprints, substructure search. |
| `Science/Chemistry/OpenBabel` | Chemical file-format conversion and molecular structure handling. |
| `Science/Chemistry/Quantum` | Quantum-chemistry and molecular-modeling computations. |
| `Science/Chemistry/MolecularDynamics` | Molecular dynamics simulation setup and trajectory analysis. |
| `Science/Physics/Simulation` | Physics simulation engines and numerical experiments. |
| `Science/Physics/HEP` | High-energy / particle physics data analysis frameworks. |
| `Science/Astronomy/AstroPy` | Astronomical data handling: coordinates, time, tables, WCS via AstroPy. |
| `Science/Astronomy/Imaging` | FITS image processing, photometry, and astronomical image reduction. |
| `Science/Plotting/Gnuplot` | Scripted 2D/3D scientific plotting with gnuplot. |
| `Science/Plotting/Matplotlib` | Python plotting/figure generation for publication graphics. |
| `Science/Plotting/Graphing` | Function/data graphing and graphics-language renderers. |
| `Science/Data/Formats` | Read/convert scientific data containers and array formats. |
| `Science/Data/Fitting` | Curve fitting, regression, and parameter estimation utilities. |
| `Science/Lab/Instruments` | Acquire and parse instrument/sensor output and lab device exports. |
| `Science/Lab/DataConversion` | Convert and clean raw lab/instrument data files into analysis-ready tables. |
| `Science/Notebooks/Jupyter` | Execute, convert, and batch-run computational notebooks. |
| `Science/Imaging/Microscopy` | Scientific image analysis and microscopy/segmentation pipelines. |

### Business, Finance, ERP & CRM

Automation categories for accounting, ERP, CRM, payroll, tax, invoicing, e-commerce, and financial-reporting tools — vendor-specific apps under <Vendor>/<App>/<Area> and cross-app money workflows under Finance/<Sub>.

| Category | What belongs here |
|---|---|
| `QuickBooks/Desktop` | Automating Intuit QuickBooks Desktop (QBXML/SDK) — company-file operations, list and transaction CRUD. |
| `QuickBooks/Online` | QuickBooks Online API automation — invoices, bills, journal entries, OAuth-backed sync. |
| `QuickBooks/Reports` | Pulling and exporting QuickBooks reports (P&L, balance sheet, A/R aging). |
| `Xero/Accounting` | Xero API automation — contacts, invoices, bank transactions, manual journals. |
| `Xero/Reports` | Xero financial-report extraction and export. |
| `Sage/Accounting` | Sage 50/Sage Intacct/Sage Business Cloud automation — ledger and transaction operations. |
| `SAP/FICO` | SAP ERP Finance & Controlling automation — postings, master data, BAPI/RFC calls. |
| `SAP/MM` | SAP Materials Management — purchase orders, goods receipt, vendor master. |
| `SAP/SD` | SAP Sales & Distribution — sales orders, deliveries, billing documents. |
| `SAP/Reports` | SAP report extraction and data export (SE16/queries/transaction dumps). |
| `Dynamics/365Finance` | Microsoft Dynamics 365 Finance & Operations — GL, AP/AR, data-entity import/export. |
| `Dynamics/BusinessCentral` | Dynamics 365 Business Central (NAV successor) automation via the BC API. |
| `NetSuite/ERP` | Oracle NetSuite automation — SuiteScript/REST/SuiteTalk record CRUD and saved searches. |
| `Odoo/ERP` | Odoo automation via XML-RPC/JSON-RPC — any module (accounting, sales, inventory). |
| `Salesforce/CRM` | Salesforce object automation — leads, accounts, opportunities, bulk data loads. |
| `Salesforce/Reports` | Salesforce report and dashboard data extraction. |
| `HubSpot/CRM` | HubSpot CRM automation — contacts, companies, deals, pipeline updates. |
| `HubSpot/Marketing` | HubSpot marketing automation — lists, email campaigns, form submissions. |
| `Zoho/CRM` | Zoho CRM record automation via the Zoho API. |
| `Finance/Invoicing` | General invoice/billing generation and dispatch across tools (PDF invoices, batch billing). |
| `Finance/Payroll` | Payroll processing and remittance prep (timesheet import, pay-run, paystub export). |
| `Finance/Tax` | Tax-preparation automation — return prep, slip generation, e-file packaging. |
| `Finance/Banking` | Bank-statement and feed processing — OFX/QFX/CSV import, transaction parsing. |
| `Finance/Reconciliation` | Account and transaction reconciliation — matching, clearing, exception reports. |
| `Finance/Reporting` | Cross-app financial reporting and consolidation (statements, KPIs, roll-ups). |
| `Finance/GL` | General-ledger and chart-of-accounts utilities independent of any one ERP (journal builders, COA mapping). |
| `Ecommerce/Shopify` | Shopify store automation — products, orders, payouts, inventory sync. |
| `Ecommerce/WooCommerce` | WooCommerce (WordPress) store automation via the WooCommerce REST API. |
| `Ecommerce/Orders` | Cross-platform e-commerce order/fulfillment workflows and marketplace consolidation. |

### Archive, Compression & Backup

Tools that pack, compress, encrypt, back up, clone, sync, deduplicate, and verify data — from archive formats like 7-Zip and zstd to backup/imaging/sync engines like Robocopy, rsync, Veeam, and rclone.

| Category | What belongs here |
|---|---|
| `Archive/SevenZip` | 7-Zip create/extract/test/update operations across its many formats (7z, zip, etc.). |
| `Archive/WinRAR` | WinRAR/RAR archive creation, extraction, recovery records, and volume splitting. |
| `Archive/Zip` | Classic ZIP create/extract/update via Info-ZIP and platform zip tooling. |
| `Archive/Tar` | POSIX tarball bundling and extraction, including compressed tar variants. |
| `Archive/Inspect` | List, browse, and test the contents of an archive without full extraction. |
| `Compression/Gzip` | Single-stream gzip/DEFLATE compression and decompression. |
| `Compression/Zstd` | Zstandard compression with tunable levels and long-range matching. |
| `Compression/Xz` | XZ/LZMA high-ratio compression for distribution and archival. |
| `Compression/Bzip2` | bzip2 block-sorting compression and its parallel variants. |
| `Compression/Brotli` | Brotli compression, common for web assets and static payloads. |
| `Compression/Benchmark` | Compare ratio and speed across codecs/levels to pick the right tradeoff. |
| `Backup/Robocopy` | Windows Robocopy mirror/backup jobs with retry, mirror, and logging flags. |
| `Backup/Rsync` | Incremental delta-transfer backups and mirroring over local/SSH paths. |
| `Backup/Restic` | Restic deduplicating, encrypted snapshot backups to local or cloud repos. |
| `Backup/Borg` | BorgBackup deduplicating, compressed, encrypted repository backups. |
| `Backup/Duplicati` | Duplicati scheduled encrypted backups to cloud and network targets. |
| `Backup/Veeam` | Veeam VM/agent backup, restore, and job control. |
| `Backup/Schedule` | Define and trigger scheduled/automated backup jobs and retention policies. |
| `Imaging/Clone` | Disk/partition cloning and full-image capture and restore. |
| `Imaging/Format` | Convert, mount, and manage disk-image container formats. |
| `Sync/Rclone` | rclone sync/copy/mount against cloud and remote object storage. |
| `Sync/FreeFileSync` | FreeFileSync two-way/mirror folder comparison and synchronization batch jobs. |
| `Sync/Folder` | General local/peer folder synchronization and continuous file replication. |
| `Dedup/Files` | Find and remove duplicate files to reclaim space before/after archiving. |
| `Integrity/Checksum` | Generate and verify hashes/manifests to confirm archive and file integrity. |
| `Integrity/Repair` | Add recovery data and repair corrupted archives or file sets. |
| `Encryption/AtRest` | Encrypt files, folders, and archives at rest for secure storage and transport. |

### Virtualization & Remote Access

Tools that create, control, and connect to virtual machines and remote/headless systems — hypervisor lifecycle automation, snapshots/cloning/provisioning, and remote-access sessions over RDP/SSH/VNC plus tunnels and file transfer.

| Category | What belongs here |
|---|---|
| `VMware/Workstation/VMs` | Lifecycle of local VMware Workstation/Player guests via vmrun/vmcli (power, register, list). |
| `VMware/Workstation/Snapshots` | Create, revert, list, and delete Workstation VM snapshots. |
| `VMware/Workstation/Guest` | In-guest operations on Workstation VMs via VMware Tools (run programs, copy files, capture). |
| `VMware/vSphere/VMs` | ESXi/vCenter VM power and inventory operations via govc/PowerCLI/pyVmomi. |
| `VMware/vSphere/Provisioning` | Clone, deploy-from-template, and OVF/OVA import/export against vCenter/ESXi. |
| `VMware/vSphere/Snapshots` | Datacenter-side snapshot management for vSphere-managed VMs. |
| `VirtualBox/VMs` | Oracle VirtualBox guest lifecycle and inventory via VBoxManage. |
| `VirtualBox/Snapshots` | Take, restore, and delete VirtualBox snapshots. |
| `VirtualBox/Provisioning` | Clone VMs and import/export appliances in VirtualBox. |
| `VirtualBox/Guest` | In-guest command execution and file copy via Guest Additions. |
| `HyperV/VMs` | Microsoft Hyper-V guest power and inventory via the Hyper-V PowerShell module. |
| `HyperV/Checkpoints` | Create, apply, and remove Hyper-V checkpoints (snapshots). |
| `HyperV/Provisioning` | Create new VMs, export/import, and clone Hyper-V guests. |
| `WSL/Distros` | Windows Subsystem for Linux distro lifecycle, import/export, and default selection. |
| `WSL/Exec` | Run Linux commands and launch sessions inside a WSL distro from Windows. |
| `QEMU/VMs` | QEMU/KVM guest lifecycle and domain control via libvirt/virsh. |
| `QEMU/Snapshots` | QEMU/libvirt snapshot and qcow2 image snapshot management. |
| `QEMU/Disks` | qcow2/raw disk image creation, conversion, and resizing for QEMU guests. |
| `QEMU/Provisioning` | Define/clone libvirt domains and build images for KVM provisioning. |
| `Vagrant/Boxes` | Cross-hypervisor dev-VM provisioning and box lifecycle via Vagrant. |
| `RemoteAccess/RDP` | Launch and configure Windows Remote Desktop sessions and .rdp files. |
| `RemoteAccess/SSH` | Open SSH sessions, manage keys, and run remote commands. |
| `RemoteAccess/Tunnels` | Port forwarding, SOCKS proxies, and exposed-tunnel setup over SSH or tunneling services. |
| `RemoteAccess/FileTransfer` | Move files to/from remote hosts over SSH/SCP/SFTP/rsync. |
| `RemoteAccess/VNC` | Start, connect to, and configure VNC screen-sharing sessions. |
| `RemoteAccess/TeamViewer` | TeamViewer unattended-access connect and session control via its CLI/API. |
| `RemoteAccess/AnyDesk` | AnyDesk remote-session launch and unattended-access configuration. |
| `RemoteAccess/Mesh` | Self-hosted/open remote-control tools for fleet access and screen sharing. |
| `RemoteAccess/RemoteExec` | Cross-host remote command execution and admin without an interactive desktop. |

### Utilities & Personal

General-purpose desktop utilities and personal-productivity tools — clipboard, screenshots, color/measure, window and launcher management, note-taking apps, secrets/QR, calculators/converters, time tracking, and personal macro automation.

| Category | What belongs here |
|---|---|
| `Utilities/Clipboard` | Clipboard history, transforms, and paste-as utilities driven from CLI. |
| `Utilities/Screenshot` | Screen and region capture, scrolling capture, and image grab tooling. |
| `Utilities/Annotation` | Mark-up, redaction, and arrow/box annotation of captured images. |
| `Utilities/ColorPicker` | Eyedropper, on-screen color sampling, and palette extraction. |
| `Utilities/ScreenMeasure` | On-screen rulers, pixel measuring, and crosshair/loupe magnifiers. |
| `Utilities/Window` | Window tiling, snapping, always-on-top, and layout save/restore. |
| `Utilities/Desktop` | Virtual desktop switching, monitor arrangement, and wallpaper control. |
| `Utilities/Launcher` | App launchers, command palettes, and quick-run shortcut tools. |
| `Utilities/Tray` | System-tray menu actions and notification/toast utilities. |
| `Utilities/QRBarcode` | Generate and decode QR codes and barcodes. |
| `Utilities/Calculator` | Expression calculators, base/number-base, and scientific compute helpers. |
| `Utilities/Converters` | Unit, currency, timezone, and format conversion utilities. |
| `Utilities/Magnifier` | Screen zoom, magnification, and accessibility enlargement tools. |
| `Personal/Notes` | General quick-note capture and scratchpad tooling (app-agnostic). |
| `Obsidian/Vault` | Obsidian vault management — open, sync, index, and backup vaults. |
| `Obsidian/Notes` | Obsidian note creation, templating, and daily-note automation. |
| `Notion/Pages` | Notion page create/update and database row automation via API. |
| `Personal/Secrets` | Password and secret generation, passphrase, and token utilities. |
| `Personal/Vault` | Local secret/credential vault entry, lookup, and copy-to-clipboard. |
| `Personal/TimeTracking` | Time logging, work-session tracking, and timesheet capture. |
| `Personal/Pomodoro` | Pomodoro and focus-timer utilities with break cycles. |
| `Personal/Reminders` | Personal reminders, alarms, and timed notification tools. |
| `AutoHotkey/Macros` | AutoHotkey personal macros, hotstrings, and text-expansion scripts. |
| `AutoHotkey/Hotkeys` | AutoHotkey global hotkey binding and remapping definitions. |
| `Personal/Automation` | Cross-app personal automation and macro recording (non-AHK). |
| `Personal/Bookmarks` | Bookmark and quick-link management and launching. |
| `Personal/Snippets` | Text-snippet libraries and template-text insertion utilities. |

### ScripTree & Demos (meta)

Meta-tooling for ScripTree itself — building, releasing, vendoring dependencies, branding, catalog/forest authoring and management — plus the bundled demo and example tools that teach the catalog formats.

| Category | What belongs here |
|---|---|
| `ScripTree` | Catch-all top-level for ScripTree self-management tools; keep as the stable brand top segment that everything below folds into. Tools land here directly only if they don't fit a more specific sub-area. |
| `ScripTree/Build` | Compiling, packaging, and producing portable/installable ScripTree builds and release artifacts (the dev side of shipping a version). |
| `ScripTree/Release` | Release orchestration: tagging, changelog assembly, GitHub release/asset upload, version-held reconciliation, the two-tree deploy step. |
| `ScripTree/Distribution` | Shipping a finished build to users — portable zips, desktop shortcuts, deploy-target mirroring to R:\Scriptreeapps. Mirrors the existing 'Distribution' management folder. |
| `ScripTree/Dependencies` | Vendored/bundled runtime dependency management: refreshing per-tool lib/ folders, auditing pinned vs installed packages, drift reports. Mirrors the existing 'Dependencies' management folder. |
| `ScripTree/Branding` | Visual identity assets for tools and the app: app/tool icons, logos, color/badge generation. Mirrors the existing 'Branding' management folder. |
| `ScripTree/Documentation` | Producing and refreshing docs/help: automated screenshots for docs, README/help-file generation, LLM-doc sync. Mirrors the existing 'Documentation' management folder. |
| `ScripTree/Catalog` | Authoring, validating, and migrating the catalog files themselves (.scriptree / .scriptreetree): schema validation, v2->v3 widget migration, category/field-order linting. |
| `ScripTree/Forest` | Workspace/forest-hub management: .scriptreeforest and .scriptreering layouts, cell/cluster arrangement, dock/undock and reflow utilities. |
| `ScripTree/Config` | Runtime settings and environment: scriptree.ini editing, path/profile management, resetting or backing up local config (never committed). |
| `ScripTree/Diagnostics` | Health, logging, and troubleshooting of a ScripTree install: log capture, environment dump, dependency/COM-attach sanity checks, bug-report bundles. |
| `Demos` | Canonical home for bundled demo/example tools that showcase ScripTree features and catalog patterns. RECONCILIATION: the shipped catalog has both 'Demo' (singular) and 'Demos' (plural) — standardize on 'Demos' and migrate the two 'Demo' files (regex-tester, deselect-to-act) to it so the forest folds them into one cell instead of two. |
| `Demos/Widgets` | Demos that exercise specific param types and widgets (radio, boolean, number, file/save pickers, action buttons) so authors can see each widget rendered. |
| `Demos/Patterns` | Demos illustrating catalog authoring patterns: dynamic choices_provider/depends_on, repeating argument groups, conditional flags, working_directory usage. |
| `Demos/Examples` | Worked end-to-end example trees that wrap real CLI tools or workflows as teaching references (e.g. the user_management example tree). |

---

**Maintaining this list:** add new categories here AND to `scriptree/resources/category_catalog.json` (or regenerate). The canonical rule: a category's top segment should be a known domain/vendor from this catalog; if you need a genuinely new domain, add it here first so humans and LLMs converge on it. See also `docs/LLM/category_authoring.md` for how the `category` field drives forest folding and the on-disk folder layout.
