"""Find mistranslations module."""

import json
import os
import re


STRICT_DICTIONARY = {
    "嗯": ["Mm", "Hmm", "Yeah", "Mhm"],
    "嗯？": ["Huh?", "Hmm?", "What?", "Mm?"],
    "哦": ["Oh", "Ooh"],
    "啊": ["Ah", "Oh"],
    "呀": ["Ah", "Oh", "Ya"],
    "哈": ["Ha", "Haha"],
    "唉": ["Sigh", "Alas", "Ah"],
    "喂": ["Hey", "Hello", "Yo"],
    "嗨": ["Hi", "Hey"],
    "诶": ["Eh", "Hey", "Huh"],
    "呃": ["Uh", "Um", "Er"],
    "咦": ["Huh", "Eh", "Hmm"],
    "好的": ["Okay", "OK", "Alright", "Fine", "Sure"],
    "是的": ["Yes", "Yeah", "Right", "Correct"],
    "不是": ["No", "Nope", "Not"],
    "对": ["Right", "Correct", "Yes", "Yeah"],
    "不对": ["Wrong", "Incorrect", "No", "Not right"],
    "什么": ["What"],
    "什么？": ["What?", "Huh?"],
    "为什么": ["Why", "How come"],
    "怎么": ["How", "Why", "What"],
    "可以": ["Sure", "Okay", "Can", "Fine", "Alright"],
    "不行": ["No", "Can't", "Not allowed"],
    "知道": ["I know", "Got it", "Understand"],
    "不知道": ["I don't know", "No idea", "Don't know"],
    "谢谢": ["Thank you", "Thanks", "Thank you very much"],
    "多谢": ["Thanks", "Thank you"],
    "抱歉": ["Sorry", "Apologies"],
    "对不起": ["I'm sorry", "Sorry", "Forgive me"],
    "没关系": ["It's okay", "It's fine", "No worries", "Never mind"],
    "没事": ["It's fine", "I'm fine", "No worries", "Nothing"],
    "再见": ["Goodbye", "See you", "Bye"],
    "你好": ["Hello", "Hi", "Greetings"],
    "等等": ["Wait", "Hold on", "Etc.", "And so on"],
    "算了": ["Never mind", "Forget it", "Let it go"],
    "走吧": ["Let's go", "Let's head out"],
    "来吧": ["Come on", "Let's go", "Bring it on"],
    "加油": ["Keep it up", "Come on", "You can do it"],
    "小心": ["Careful", "Watch out", "Be careful"],
    "危险": ["Danger", "Dangerous"],
    "停下": ["Stop", "Halt"],
    "住手": ["Stop", "Stop it", "Hands off"],
    "明白": ["Understood", "I see", "Got it"],
    "收到": ["Received", "Roger", "Got it"],
    "了解": ["Understood", "I see", "Got it"],
    "知道了": ["Got it", "Understood", "I see"],
    "没问题": ["No problem", "Sure", "Fine"],
    "当然": ["Of course", "Naturally", "Certainly"],
    "也许": ["Maybe", "Perhaps", "Possibly"],
    "可能": ["Maybe", "Perhaps", "Possibly"],
    "确定": ["Sure", "Certain", "Confirmed"],
    "不确定": ["Not sure", "Uncertain", "Unsure"],
}


def contains_chinese(text):
    if not text: return False
    return bool(re.search(r'[\u4e00-\u9fff]', text))


def check_strict_dictionary(cn_text, en_text):
    cn_clean = cn_text.strip()
    if cn_clean not in STRICT_DICTIONARY:
        return None
    allowed = STRICT_DICTIONARY[cn_clean]
    en_lower = en_text.lower().strip()
    for a in allowed:
        if a.lower() in en_lower:
            return None
    return {"type": "DICTIONARY_MISMATCH", "expected": allowed, "actual": en_text.strip()}


def check_punctuation(cn_text, en_text):
    cn = cn_text.strip()
    en = en_text.strip()
    if cn.endswith('？') and not en.endswith('?'):
        return {"type": "MISSING_QUESTION_MARK", "cn_ending": "？", "en_ending": en[-3:]}
    if cn.endswith('！') and not en.endswith('!'):
        return {"type": "MISSING_EXCLAMATION", "cn_ending": "！", "en_ending": en[-3:]}
    return None


def check_length(cn_text, en_text):
    cn = cn_text.strip()
    en = en_text.strip()
    if len(cn) < 8 and len(en) > 30:
        return {"type": "SUSPICIOUS_LENGTH", "cn_length": len(cn), "en_length": len(en)}
    return None


def run_find_errors(source_file, translated_file, output_file, log_queue):
    """Quét lỗi dịch thuật, kết quả lưu vào output_file."""
    try:
        log_queue.put("[INFO] Đang tải dữ liệu...")
        
        if not os.path.exists(source_file):
            log_queue.put(f"[ERROR] Không tìm thấy source: {source_file}")
            return
        if not os.path.exists(translated_file):
            log_queue.put(f"[ERROR] Không tìm thấy translated: {translated_file}")
            return
        
        with open(source_file, 'r', encoding='utf-8') as f:
            source_data = json.load(f)
        with open(translated_file, 'r', encoding='utf-8') as f:
            translated_data = json.load(f)
        
        cn_texts = source_data.get("texts", {})
        en_texts = translated_data.get("texts", {})
        
        log_queue.put(f"[OK] Source: {len(cn_texts)} câu")
        log_queue.put(f"[OK] Translated: {len(en_texts)} câu\n")
        log_queue.put("[INFO] Đang quét lỗi...")
        
        suspicious = {}
        stats = {"DICTIONARY_MISMATCH": 0, "MISSING_QUESTION_MARK": 0,
                 "MISSING_EXCLAMATION": 0, "SUSPICIOUS_LENGTH": 0}
        
        total = len(cn_texts)
        for i, (key, cn_text) in enumerate(cn_texts.items(), 1):
            if key not in en_texts:
                continue
            en_text = en_texts[key]
            if contains_chinese(en_text):
                continue
            
            issues = []
            dict_issue = check_strict_dictionary(cn_text, en_text)
            if dict_issue:
                issues.append(dict_issue)
                stats["DICTIONARY_MISMATCH"] += 1
            punc_issue = check_punctuation(cn_text, en_text)
            if punc_issue:
                issues.append(punc_issue)
                stats[punc_issue["type"]] += 1
            len_issue = check_length(cn_text, en_text)
            if len_issue:
                issues.append(len_issue)
                stats["SUSPICIOUS_LENGTH"] += 1
            
            if issues:
                suspicious[key] = {"cn_text": cn_text, "en_text": en_text, "issues": issues}
            
            if i % 10000 == 0:
                log_queue.put(f"[PROGRESS] {i:,}/{total:,} câu đã quét")
        
        os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
        with open(output_file, 'w', encoding='utf-8', newline='\n') as f:
            json.dump({
                "format": "gfl2-langpackage-by-text-1",
                "texts": {
                    k: {"CN": d["cn_text"], "EN": d["en_text"], "ISSUES": d["issues"]}
                    for k, d in suspicious.items()
                }
            }, f, ensure_ascii=False, indent=2)
        
        log_queue.put("")
        log_queue.put("=" * 60)
        log_queue.put("[DONE] QUÉT HOÀN TẤT!")
        log_queue.put("=" * 60)
        log_queue.put(f"[INFO] Tổng số câu nghi ngờ: {len(suspicious)}")
        for et, c in stats.items():
            if c > 0:
                log_queue.put(f"  • {et}: {c}")
        log_queue.put(f"[DONE] File kết quả: {output_file}")
        
    except Exception as e:
        log_queue.put(f"[ERROR] {e}")
        import traceback
        log_queue.put(traceback.format_exc())
    finally:
        log_queue.put("__DONE__")