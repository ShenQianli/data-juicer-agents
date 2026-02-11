# -*- coding: utf-8 -*-

from data_juicer_agents.tools.router_helpers import select_workflow


def test_select_workflow_for_rag():
    workflow = select_workflow("please clean rag corpus and retrieval chunks")
    assert workflow == "rag_cleaning"


def test_select_workflow_for_multimodal_dedup():
    workflow = select_workflow("do image duplicate removal for multimodal dataset")
    assert workflow == "multimodal_dedup"


def test_select_workflow_prefers_rag_for_text_dedup_only():
    workflow = select_workflow("prepare rag documents: normalize, length filter, deduplicate")
    assert workflow == "rag_cleaning"


def test_select_workflow_prefers_multimodal_for_image_cues():
    workflow = select_workflow("图文数据近重复清理，降低训练数据冗余")
    assert workflow == "multimodal_dedup"


def test_select_workflow_prefers_multimodal_for_multimodal_keyword():
    workflow = select_workflow("对多模态数据集做重复样本过滤")
    assert workflow == "multimodal_dedup"
