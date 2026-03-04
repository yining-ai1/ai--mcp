# -*- coding: utf-8 -*-
"""Video tool declarations (name / description / inputSchema)."""


def get_video_tools() -> dict:
    """Return video tools dict keyed by tool name."""
    return {
        "video_generate": {
            "name": "video_generate",
            "description": "根据文本提示生成视频（T2V）；若提供 image 则为图文生视频（I2V）",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "视频生成提示词"},
                    "negative_prompt": {"type": "string", "description": "负面提示词（可选）"},
                    "width": {"type": "integer", "description": "视频宽度", "default": 480},
                    "height": {"type": "integer", "description": "视频高度", "default": 480},
                    "num_frames": {"type": "integer", "description": "帧数（可选，默认 24）"},
                    "fps": {"type": "integer", "description": "帧率（可选，默认 24）"},
                    "seed": {"type": "integer", "description": "随机种子（可选）"},
                    "image": {
                        "type": "string",
                        "description": "I2V 首帧/参考图：图片 URL 或 base64/data URL。不传则为纯 T2V",
                    },
                },
                "required": ["prompt"],
            },
        },
        "video_status": {
            "name": "video_status",
            "description": "查询视频生成任务状态",
            "inputSchema": {
                "type": "object",
                "properties": {"task_id": {"type": "string", "description": "任务ID"}},
                "required": ["task_id"],
            },
        },
        "video_download": {
            "name": "video_download",
            "description": "根据 task_id 下载已完成的视频，返回 base64 编码的视频数据（mp4）",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "视频生成任务ID（由 video_generate 返回）",
                    },
                },
                "required": ["task_id"],
            },
        },
    }
