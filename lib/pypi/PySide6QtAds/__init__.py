import platform

if platform.system() == 'Windows':
	import os, PySide6, shiboken6
	with os.add_dll_directory(os.path.dirname(PySide6.__file__)), \
	     os.add_dll_directory(os.path.dirname(shiboken6.__file__)):
		from .PySide6QtAds import ads
else:
	# Runtime library dependencies resolved via rpath
	from .PySide6QtAds import ads

# DockWidgetArea
DockWidgetArea = ads.DockWidgetArea
NoDockWidgetArea = ads.NoDockWidgetArea
LeftDockWidgetArea = ads.LeftDockWidgetArea
RightDockWidgetArea = ads.RightDockWidgetArea
TopDockWidgetArea = ads.TopDockWidgetArea
BottomDockWidgetArea = ads.BottomDockWidgetArea
CenterDockWidgetArea = ads.CenterDockWidgetArea
InvalidDockWidgetArea = ads.InvalidDockWidgetArea
OuterDockAreas = ads.OuterDockAreas
AllDockAreas = ads.AllDockAreas

# eTabIndex
TabDefaultInsertIndex = ads.TabDefaultInsertIndex
TabInvalidIndex = ads.TabInvalidIndex

# SideBarLocation
SideBarLeft = ads.SideBarLeft
SideBarTop = ads.SideBarTop
SideBarBottom = ads.SideBarBottom
SideBarRight = ads.SideBarRight
SideBarNone = ads.SideBarNone

# eBitwiseOperator
BitwiseAnd = ads.BitwiseAnd
BitwiseOr = ads.BitwiseOr

# eDragState
DraggingInactive = ads.DraggingInactive
DraggingMousePressed = ads.DraggingMousePressed
DraggingTab = ads.DraggingTab
DraggingFloatingWidget = ads.DraggingFloatingWidget

# eIcon
TabCloseIcon = ads.TabCloseIcon
AutoHideIcon = ads.AutoHideIcon
DockAreaMenuIcon = ads.DockAreaMenuIcon
DockAreaUndockIcon = ads.DockAreaUndockIcon
DockAreaCloseIcon = ads.DockAreaCloseIcon
DockAreaMinimizeIcon = ads.DockAreaMinimizeIcon
IconCount = ads.IconCount

# TitleBarButton
TitleBarButtonTabsMenu = ads.TitleBarButtonTabsMenu
TitleBarButtonUndock = ads.TitleBarButtonUndock
TitleBarButtonClose = ads.TitleBarButtonClose
TitleBarButtonAutoHide = ads.TitleBarButtonAutoHide
TitleBarButtonMinimize = ads.TitleBarButtonMinimize

# Classes
CDockAreaTabBar = ads.CDockAreaTabBar
CDockAreaTitleBar = ads.CDockAreaTitleBar
CDockAreaWidget = ads.CDockAreaWidget
CDockComponentsFactory = ads.CDockComponentsFactory
CDockContainerWidget = ads.CDockContainerWidget
CDockFocusController = ads.CDockFocusController
CDockManager = ads.CDockManager
CDockSplitter = ads.CDockSplitter
CDockOverlay = ads.CDockOverlay
CDockOverlayCross = ads.CDockOverlayCross
CDockWidget = ads.CDockWidget
CDockWidgetTab = ads.CDockWidgetTab
CDockingStateReader = ads.CDockingStateReader
CElidingLabel = ads.CElidingLabel
CFloatingDockContainer = ads.CFloatingDockContainer
CFloatingDragPreview = ads.CFloatingDragPreview
IFloatingWidget = ads.IFloatingWidget
CIconProvider = ads.CIconProvider
CSpacerWidget = ads.CSpacerWidget
CTitleBarButton = ads.CTitleBarButton
