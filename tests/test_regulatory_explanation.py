"""Residency is a hard policy allowlist, independent of objective attractiveness."""
from copy import deepcopy
import json
import pytest
from src.config import load
from src.direct import preprocess
from src.validation import validate
from src import pipeline
from src.placement_explanation import build
from src.demo import DemoConfig, explain
from tests.test_pipeline import ROOT, scenario, mock_ai


def inputs():
    c,_=load(ROOT/'config/scenario.yaml')
    return c,c['applications']['applications'][0],c['existing_portfolio']['applications']


def placement(a, sid='AWS_HK'):
    return dict(application_id=a['id'],environments={e:sid for e in a['environments']},dr_site_id=sid,failure_domain_contract='INDEPENDENT_LOCAL_DOMAINS')


@pytest.mark.parametrize('field',['approved_hosting_countries','approved_processing_countries'])
@pytest.mark.parametrize('env',['PROD','DEV','SIT','UAT'])
def test_sg_only_blocks_hk_in_every_environment(field,env):
    c,a,p=inputs();c['regulatory']['policies'][0][field]=['SG']
    domains,_,_=preprocess(c,[a],p)
    assert 'AWS_HK' not in domains[a['id'],env]
    audit=validate(c,a,p,placement(a))
    assert not audit['valid'] and f'POLICY_DENIAL:{env}:AWS_HK' in audit['reasons']


@pytest.mark.parametrize('sg_only',[False,True])
def test_compiler_and_independent_validator_agree_for_every_site(sg_only):
    c,a,p=inputs();a['environments']=['PROD']
    if sg_only:
        c['regulatory']['policies'][0]['approved_hosting_countries']=['SG']
    domains,_,_=preprocess(c,[a],p)
    for site in c['sites']['sites']:
        assert (site['id'] in domains[a['id'],'PROD']) == validate(c,a,p,placement(a,site['id']))['valid']


@pytest.mark.parametrize('attraction',['cheaper','faster'])
def test_ineligible_hk_cannot_win(tmp_path,attraction):
    def change(key,data):
        if key=='applications':data['applications'][0]['environments']=['PROD']
        if key=='regulatory':data['policies'][0]['approved_hosting_countries']=['SG']
        if key=='cost' and attraction=='cheaper':
            data['per_vcpu_monthly']['AWS_HK']=0;data['per_site_monthly_fixed']['AWS_HK']=0
        if key=='dependencies' and attraction=='faster':data['latency_matrix_ms']['AWS_HK']['AWS_HK']=0
    _,result=pipeline.run(scenario(tmp_path,change),tmp_path/'out')
    assert result.status=='RECOMMENDED'
    assert result.placement['environments']=={'PROD':'AWS_SG'}
    assert result.placement['dr_site_id']=='AWS_SG'


def test_sg_only_four_environments_are_infeasible(tmp_path):
    def change(key,data):
        if key=='regulatory':data['policies'][0]['approved_hosting_countries']=['SG']
    folder,result=pipeline.run(scenario(tmp_path,change),tmp_path/'out')
    assert result.status=='INFEASIBLE'
    audit=json.loads((folder/'constraint_audit.json').read_text())
    assert audit['constraints']==[] and 'No accepted placement' in audit['unavailable_reason']


@pytest.mark.parametrize('violation',['separate_dr','recovery','missing_policy'])
def test_dr_and_missing_policy_fail_closed(violation):
    c,a,p=inputs();chosen=placement(a)
    if violation=='separate_dr':chosen['dr_site_id']='AZURE_HK'
    if violation=='recovery':
        next(s for s in c['sites']['sites'] if s['id']=='AWS_HK')['recovery']['rto_minutes']=61
    if violation=='missing_policy':c['regulatory']['policies']=[]
    assert not validate(c,a,p,chosen)['valid']


@pytest.mark.parametrize('mode',['REFERENCE_FALLBACK','AI_ASSISTED'])
def test_report_matches_verified_facts_and_mode(tmp_path,mode):
    config=ROOT/'config/scenario.yaml';kwargs={}
    if mode=='AI_ASSISTED':
        runtime=tmp_path/'runtime';kwargs=dict(runtime_evidence=runtime,adapter=mock_ai(config,runtime))
    folder,result=pipeline.run(config,tmp_path/'out',mode=mode,**kwargs)
    report=json.loads((folder/'constraint_audit.json').read_text())
    assert result.status=='RECOMMENDED'
    assert len(report['selected'])==5
    assert all(r['status'] in ('PASS','NOT_APPLICABLE') for r in report['constraints'])
    assert len([r for r in report['constraints'] if r['constraint']=='residency_and_policy'])==5
    assert report['objective']['score']==pytest.approx(.2)
    assert report['objective']['score']==pytest.approx(result.solver['incumbent'])
    other=report['alternatives']['displayed_alternatives'][0]
    assert other['classification']=='FEASIBLE_LOWER_RANKED'
    assert other['score_delta']==pytest.approx(.4)
    assert report['ai']['mode']==mode and not report['ai']['genuine_optimind_inference']
    assert report['ai']['fallback_used']==(mode=='REFERENCE_FALLBACK')
    assert report['alternatives']['enumeration_complete']
    assert 'real-world compliance' in (folder/'placement_explanation.md').read_text()
    c,a,p=inputs()
    tampered=deepcopy(result);tampered.placement['dr_site_id']='AZURE_HK'
    with pytest.raises(ValueError,match='AUDIT_FAILED'):build(c,a,p,tampered,mode)
    result.explanation=explain(c,a,p,result.placement,DemoConfig(max_explanation_assignments=1))
    partial=build(c,a,p,result,mode)
    assert not partial['alternatives']['enumeration_complete']
    assert partial['alternatives']['not_evaluated_reason']
