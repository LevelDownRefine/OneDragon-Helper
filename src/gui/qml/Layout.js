.pragma library

// 固定画布与整窗裁切，共用逻辑像素。
var windowWidth = 1280
var windowHeight = 720
var windowCornerRadius = 16

// 任务卡位置决定弹出菜单在窗口内的可用空间。
var taskCardX = 128
var taskCardY = 392
var popupAnchorGap = 4
var popupEdgeMargin = 8

// 任务行（日常 / 周常）共用行高：36 高的图标居中，上下各 10 留白。
// 相邻两行净距 = 10 + 10 = 20；两区之间不另加间距（区块外沿直接相接），
// 使「日常→日常」与「日常→周常」的视觉距离一致。
var taskRowHeight = 56

// 卡片底部留白：最后一个区块（有周常则是周常区，否则是日常区）到卡片的距离，
// 两种形态下一致；行自带的下留白不再重复计入。
var cardBottomPad = 16
