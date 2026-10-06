# 内置敏感词库与转换数据（第三方数据）

| 文件 | 内容 | 来源 | 许可证 |
| --- | --- | --- | --- |
| sensitive_words.txt | 黑名单（自动生成，勿手改） | houbb/sensitive-word-data | Apache-2.0 |
| sensitive_allow.txt | 白名单（命中词若落在白名单词内则忽略） | 上游 allow + 本项目 | - |
| sensitive_t2s.txt | 繁 -> 简 映射（3221 条） | BYVoid/OpenCC TSCharacters.txt | Apache-2.0 |
| sensitive_pinyin.txt | 词库词的拼音（无音调，仅 <=4 字词） | mozillazg/pinyin-data | MIT |

- 生成：scripts/import_sensitive_words.py（默认排除政治类标签 0，最短 2 字）
- 词库词数：约 6.2 万；运行时用纯 Python DFA（src/core/sensitive.py），不依赖 Java / 第三方库

修改词库请改 allow 文件、或在上游数据更新后重跑生成脚本；
二次分发本目录内容时，请保留本说明与各上游许可证（Apache-2.0 / MIT）。
