import json
from rag_app.config import load_config
from rag_app.__main__ import run_questions
config=load_config().model_copy(update={'generation_model':'qwen3.5:9b','num_predict':3000})
questions=json.load(open('evaluation/questions.sample.json',encoding='utf-8'))
questions += [{'id':'q4','question':'这篇论文作者运行 TempQuestions 时的 GPU 峰值显存是多少？'}, {'id':'q5','question':'TempQuestions 有多少个时间问题？这篇论文作者运行它时的 GPU 峰值显存是多少？'}, {'id':'q6','question':'内部知识冲突与外部知识冲突有什么区别？'}]
print(run_questions(config,questions,True))
