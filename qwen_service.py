"""
千问/阿里云百炼 AI 服务封装。

安全说明：
- API Key 只从环境变量或 .env 中读取，不要写死在代码里。
- 如果要分析 2MB-20MB 的冲扫大图，视觉模型调用前会自动压缩为较小 JPEG，避免请求体过大。
- AI 评分只作为“建议评分”，系统会保留手动修改入口，避免模型判断替代个人审美。
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv
from PIL import Image, ImageOps
from utils import SCORE_DEFAULT, SCORE_MAX, SCORE_MIN, final_score_from_parts

load_dotenv()

try:
    from openai import OpenAI
except Exception:  # 允许未安装依赖时页面给出友好提示
    OpenAI = None  # type: ignore


@dataclass
class QwenConfig:
    api_key: str
    base_url: str
    text_model: str
    vision_model: str
    text_models: List[str]
    vision_models: List[str]
    enable_vision: bool


DEFAULT_TEXT_MODELS = ["qwen-plus", "qwen3.6-flash", "qwen3.5-flash", "qwen-turbo"]
DEFAULT_VISION_MODELS = ["qwen-vl-plus", "qwen3-vl-plus", "qwen3-vl-flash", "qwen-vl-max"]


def _model_candidates(env_name: str, primary: str, defaults: List[str]) -> List[str]:
    raw = os.getenv(env_name, "").strip()
    configured = [item.strip() for item in raw.split(",") if item.strip()]
    candidates = [primary] + configured + defaults
    result = []
    for model in candidates:
        if model and model not in result:
            result.append(model)
    return result


def get_qwen_config() -> QwenConfig:
    text_model = os.getenv("QWEN_TEXT_MODEL", "qwen-plus").strip()
    vision_model = os.getenv("QWEN_VISION_MODEL", "qwen-vl-plus").strip()
    return QwenConfig(
        api_key=os.getenv("DASHSCOPE_API_KEY", "").strip(),
        base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").strip(),
        text_model=text_model,
        vision_model=vision_model,
        text_models=_model_candidates("QWEN_TEXT_MODELS", text_model, DEFAULT_TEXT_MODELS),
        vision_models=_model_candidates("QWEN_VISION_MODELS", vision_model, DEFAULT_VISION_MODELS),
        enable_vision=os.getenv("QWEN_ENABLE_VISION", "1").strip() not in {"0", "false", "False", "否"},
    )


def qwen_is_ready() -> bool:
    cfg = get_qwen_config()
    return bool(OpenAI and cfg.api_key and cfg.base_url)


def _client():
    cfg = get_qwen_config()
    if OpenAI is None:
        raise RuntimeError("缺少 openai 依赖，请先执行：pip install -r requirements.txt")
    if not cfg.api_key:
        raise RuntimeError("未配置 DASHSCOPE_API_KEY。请在项目根目录创建 .env，或运行 setup_env_from_csv.py。")
    return OpenAI(api_key=cfg.api_key, base_url=cfg.base_url), cfg


def _is_switchable_model_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    markers = [
        "quota",
        "insufficient",
        "free allocated",
        "balance",
        "arrearage",
        "rate limit",
        "ratelimit",
        "too many requests",
        "429",
        "model not found",
        "model_not_found",
        "invalid model",
        "permission",
        "access denied",
        "forbidden",
        "403",
    ]
    return any(marker in text for marker in markers)


def _chat_completion_with_fallback(client, models: List[str], **kwargs) -> Tuple[str, str]:
    last_error: Optional[Exception] = None
    tried = []
    for model in models:
        tried.append(model)
        try:
            resp = client.chat.completions.create(model=model, **kwargs)
            return resp.choices[0].message.content or "", model
        except Exception as exc:
            last_error = exc
            if not _is_switchable_model_error(exc):
                raise
    raise RuntimeError(f"候选模型均调用失败（{', '.join(tried)}）：{last_error}") from last_error


def _safe_json_from_text(text: str) -> Dict[str, object]:
    """尽量从模型回答中提取 JSON。失败时返回空结构。"""
    text = (text or "").strip()
    candidates = []
    code_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S | re.I)
    if code_match:
        candidates.append(code_match.group(1).strip())
    fenced = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    fenced = re.sub(r"\s*```$", "", fenced)
    candidates.append(fenced.strip())
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except Exception:
            pass
    return _partial_json_fields(text)


def _partial_json_fields(text: str) -> Dict[str, object]:
    """模型输出被截断时，尽量恢复已返回的字段。"""
    data: Dict[str, object] = {}
    if not text:
        return data

    def string_field(name: str) -> str:
        match = re.search(rf'"{name}"\s*:\s*"((?:\\.|[^"\\])*)"', text, re.S)
        if not match:
            return ""
        try:
            return json.loads(f'"{match.group(1)}"')
        except Exception:
            return match.group(1).replace('\\"', '"').strip()

    for field in ["description", "reason", "score_reason"]:
        value = string_field(field)
        if value:
            data[field] = value

    tags_match = re.search(r'"suggested_tags"\s*:\s*\[(.*?)(?:\]|\n\s*"[a-zA-Z_]+")', text, re.S)
    if tags_match:
        tags = re.findall(r'"((?:\\.|[^"\\])*)"', tags_match.group(1))
        parsed_tags = []
        for tag in tags:
            try:
                parsed_tags.append(json.loads(f'"{tag}"'))
            except Exception:
                parsed_tags.append(tag.replace('\\"', '"').strip())
        if parsed_tags:
            data["suggested_tags"] = parsed_tags

    scores = _extract_scores_from_text(text)
    if scores:
        data["scores"] = scores
    return data


def _extract_scores_from_text(text: str) -> Dict[str, object]:
    score_aliases = {
        "tech_score": ["tech_score", "technical_score", "技术评分", "技术完成度"],
        "composition_score": ["composition_score", "构图评分", "构图组织"],
        "color_score": ["color_score", "色彩评分", "色彩与影调", "影调评分"],
        "emotion_score": ["emotion_score", "情绪评分", "情绪表达", "情绪与叙事"],
        "overall_score": ["overall_score", "综合评分", "总分", "平均分"],
    }
    search_area = text
    scores_match = re.search(r'"scores"\s*[:：]\s*\{(.*?)(?:\}|\n\s*"[a-zA-Z_]+")', text, re.S)
    if scores_match:
        search_area = scores_match.group(1)

    scores: Dict[str, object] = {}
    for key, aliases in score_aliases.items():
        for alias in aliases:
            patterns = [
                rf'"{re.escape(alias)}"\s*[:：]\s*"?(10(?:\.0)?|[1-9](?:\.\d+)?)\s*(?:分|星)?"?',
                rf'{re.escape(alias)}\s*[:：]\s*"?(10(?:\.0)?|[1-9](?:\.\d+)?)\s*(?:分|星)?"?',
            ]
            for pattern in patterns:
                match = re.search(pattern, search_area, re.S)
                if match:
                    value = match.group(1)
                    scores[key] = float(value) if "." in value else int(value)
                    break
            if key in scores:
                break
    return scores


def _clamp_score(value, default: float = SCORE_DEFAULT) -> float:
    """把模型返回值限制在 1.0-10.0 的 0.5 步进范围内。"""
    try:
        value = float(value)
    except Exception:
        value = default
    value = round(value * 2) / 2
    return round(max(SCORE_MIN, min(SCORE_MAX, value)), 1)


GENERIC_TAGS = {"胶片", "胶片感", "胶片质感", "横构图", "竖构图", "方构图", "风景"}


def _filter_specific_tags(tags: List[str]) -> List[str]:
    filtered = []
    for tag in tags:
        tag = str(tag).strip().replace("#", "")
        if tag in {"黑白/低饱和", "低饱和"}:
            tag = "黑白"
        if tag and tag not in GENERIC_TAGS and tag not in filtered:
            filtered.append(tag)
    return filtered


def _compact_photo_for_vision(image_path: str, max_side: int = 1280, quality: int = 82) -> str:
    """把本地大图压缩为 data:image/jpeg;base64,... 形式。"""
    with Image.open(image_path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
    encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{encoded}"


def chat_text(prompt: str, system: Optional[str] = None, temperature: float = 0.5) -> str:
    client, cfg = _client()
    content, _used_model = _chat_completion_with_fallback(
        client,
        cfg.text_models,
        messages=[
            {"role": "system", "content": system or "你是一个专业、简洁的中文胶片摄影信息分析助手。"},
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
    )
    return content


def analyze_photo_with_qwen(
    image_abs_path: str,
    roll_text: str,
    photo_text: str,
    fallback_tags: List[str],
) -> Dict[str, object]:
    """
    调用千问视觉模型分析单张照片。

    返回字段：
    - description：照片描述
    - suggested_tags：推荐标签
    - reason：分类原因
    - scores：四项评分与综合评分
    - score_reason：评分理由
    """
    client, cfg = _client()

    prompt = f"""
请你作为胶片摄影作品整理助手，分析这张照片。
严格输出一个完整 JSON 对象：不要 Markdown，不要 ```json 代码块，不要解释文字，不要在 JSON 前后添加任何内容。
所有字段必须出现；如果无法判断，字符串字段填 "-"，数组填 []，四项评分填 5.5。
scores 内的 tech_score、composition_score、color_score、emotion_score、overall_score 必须是 JSON 数字，不要写成字符串，不要带“分”或“星”。

客观评分体系：
四项评分均为 1.0-10.0 的数字，允许 0.5 分步进，必须基于画面中可观察的证据。默认合格基准为 5.5 分，只有证据明确时才上调或下调。
最终评分由系统基于四项评分进行加权和稳定性校准后计算并保留两位小数；overall_score 只作为系统展示值参考，你仍必须重点保证四项评分客观一致。
校准规则概要：构图与情绪表达权重略高；有明显短板时限制总分上限；四项表现稳定且至少三项较强时小幅加分；维度差异过大时小幅降分。不要为了抬高总分而平均给高分。

通用量表：
- 1.0-2.5：严重失败；关键主体不可读，曝光/对焦/扫描问题让画面几乎失去观看或归档价值。
- 3.0-4.5：明显较弱或低于可用基准；可辨认内容有限，缺陷清楚且影响稳定观看。
- 5.0-6.0：合格到良好；没有严重问题，普通记录照通常落在 5.0-5.5，有明确优点可到 6.0。
- 6.5-7.5：稳定优秀；优点明确，短板较少，明显高于普通记录。
- 8.0-8.5：强作品；该维度有很强证据，优点突出且短板轻微。
- 9.0-10.0：本卷代表作或卓越水准；证据非常充分，不应轻易给出。

四项评分细则：
- tech_score 技术完成度：看对焦/清晰度、曝光是否保留关键细节、主体是否可读、画面是否有明显抖动或扫描瑕疵。欠曝过曝、主体糊、关键区域不可读应降分。
- composition_score 构图组织：看主体位置、视觉重心、前中后景层次、边缘干扰、线条与留白是否服务主体。只有横竖构图本身不能加分。
- color_score 色彩与影调：看色彩是否协调、明暗层次是否稳定、肤色或主要色块是否自然、颗粒/偏色是否影响表达。不能只因“胶片感”给高分。
- emotion_score 情绪与叙事：看画面是否有明确观看动机、人物/场景关系、时间感、故事线索或记忆点。普通记录照通常为 5.0-5.5 分。

评分分布约束：
- 不要全部给整数分，也不要把整卷都集中在 5.5 或 6.0；证据略强或略弱时优先使用 0.5 分区分。
- 普通照片多数应在 5.0-6.0 分。
- 只有当至少两个维度有明确强证据时，最终评分才适合高于 7.50。
- 只有当四个维度都没有明显短板且至少两个维度达到 9.0 时，最终评分才适合高于 9.00。
- 如果无法判断某项，给 5.5 分，并在 score_reason 中说明判断依据不足。

需要返回：
{{
  "description": "80字以内的中文照片描述，优先描述可见主体、场景、光线和可归档信息",
  "suggested_tags": ["3到8个具体中文标签，避免胶片、胶片感、横构图、竖构图、风景这类过宽泛标签"],
  "reason": "30字以内，说明为什么这样分类",
  "scores": {{
    "tech_score": 1.0到10.0的数字，允许0.5小数,
    "composition_score": 1.0到10.0的数字，允许0.5小数,
    "color_score": 1.0到10.0的数字，允许0.5小数,
    "emotion_score": 1.0到10.0的数字，允许0.5小数,
    "overall_score": 按系统加权校准规则估算的两位小数
  }},
  "score_reason": "120字以内，分别概括技术、构图、色彩、情绪的评分证据，指出主要优点和主要短板"
}}

胶卷信息：{roll_text}
照片已有信息：{photo_text}
已有基础标签：{', '.join(fallback_tags) if fallback_tags else '无'}
""".strip()

    if cfg.enable_vision:
        image_url = _compact_photo_for_vision(image_abs_path)
        content, used_model = _chat_completion_with_fallback(
            client,
            cfg.vision_models,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
            temperature=0.2,
            max_tokens=1200,
        )
    else:
        # 关闭视觉模型时，退化为根据已有结构化信息生成描述和建议评分。
        content, used_model = _chat_completion_with_fallback(
            client,
            cfg.text_models,
            messages=[
                {"role": "system", "content": "你是胶片摄影照片归档助手。只返回完整 JSON 对象，不要 Markdown 或代码块。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=1200,
        )

    data = _safe_json_from_text(content)
    description = str(data.get("description") or "").strip() or content.strip()[:180]

    suggested = data.get("suggested_tags") or []
    if isinstance(suggested, str):
        suggested = [x.strip() for x in re.split(r"[,，、\s]+", suggested) if x.strip()]
    suggested = _filter_specific_tags([str(x).strip().replace("#", "") for x in suggested if str(x).strip()])

    score_data = data.get("scores") or {}
    if not isinstance(score_data, dict):
        score_data = {}
    score_data = {**_extract_scores_from_text(content), **score_data}
    scores = {
        "tech_score": _clamp_score(score_data.get("tech_score"), SCORE_DEFAULT),
        "composition_score": _clamp_score(score_data.get("composition_score"), SCORE_DEFAULT),
        "color_score": _clamp_score(score_data.get("color_score"), SCORE_DEFAULT),
        "emotion_score": _clamp_score(score_data.get("emotion_score"), SCORE_DEFAULT),
    }
    scores["overall_score"] = final_score_from_parts(scores.values())

    reason = str(data.get("reason") or "").strip()
    score_reason = str(data.get("score_reason") or "").strip()
    return {
        "description": description,
        "suggested_tags": suggested[:8],
        "reason": reason,
        "scores": scores,
        "score_reason": score_reason,
        "model": used_model,
        "raw": content,
    }


def generate_roll_summary_with_qwen(roll_text: str, photo_table_text: str, stats_text: str) -> str:
    prompt = f"""
请为这一卷胶片生成一份中文复盘总结，适合课程设计系统展示。

胶卷与冲扫信息：
{roll_text}

照片概况：
{stats_text}

照片样本：
{photo_table_text}

要求：
1. 用 4 个小标题：整体风格、优秀表现、存在不足、下次拍摄建议；
2. 不要编造不存在的器材或地点；
3. 语言自然，不要太学术；
4. 总字数控制在 350 字以内。
""".strip()
    return chat_text(prompt, system="你是胶片摄影复盘助手，擅长把照片评分、标签和冲扫信息转化为可执行建议。", temperature=0.55)
