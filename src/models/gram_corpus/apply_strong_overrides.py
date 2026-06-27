"""Apply my judgment-pass overrides to the strong_ideation column only,
for non-gold rows. Gold rows (graded in cleaned2) are left untouched.
Regenerates cleaned3 in place."""
import csv
SRC2="jpo_allGramsGreaterThan47InFreq_cleaned2.csv"
C3="jpo_allGramsGreaterThan47InFreq_cleaned3.csv"

# my per-gram strong judgment (non-gold only). y=3 vivid words leap; m=borderline/
# productive-prefix/2-words; n=abstract morpheme/glue/launchless.
OV={
"er":"n","ti":"y","on":"m","in":"m","at":"m","en":"m","an":"m","al":"n","ra":"y",
"ar":"m","ic":"n","ri":"y","li":"y","or":"m","it":"m","co":"y","ro":"y","ta":"y",
"la":"y","di":"y","un":"m","ca":"y","tr":"y","ma":"y","us":"m","na":"y","et":"m",
"si":"y","pe":"y","el":"m","ed":"m","lo":"y","mi":"y","pr":"y","ate":"m","bl":"y",
"ab":"m","to":"y","he":"y","as":"m","ul":"m","pa":"y","em":"m","po":"y","mo":"y",
"im":"m","no":"y","mp":"m","ha":"y","ho":"y","con":"m","hi":"y","sc":"y","ad":"m",
"ap":"m","id":"m","os":"n","su":"y","sp":"y","um":"m","op":"m","so":"y","sa":"y",
"be":"y","cr":"y","vi":"y","pi":"y","ant":"m","bi":"y","pl":"y","cu":"y","ess":"m",
"ga":"y","gr":"y","fi":"y","ba":"y","ph":"m","qu":"y","per":"m","ex":"m","tra":"y",
"va":"m","pro":"m","lit":"m","if":"n","fe":"y","bo":"y","do":"y","cl":"y","str":"m",
"pre":"m","ip":"y","ine":"y","rm":"m","da":"y","fu":"m","int":"m","lat":"m","fo":"y",
"br":"y","bu":"y","tri":"y","pu":"y","com":"m","ev":"m","fl":"y","rn":"m","sta":"y",
"wa":"y","nat":"m","fa":"y","mu":"m","av":"m","min":"m","ten":"m","pt":"m","ob":"m",
"tin":"m","the":"m","du":"m","gl":"y","lt":"m","ial":"n","up":"m","lin":"m","go":"y",
"gra":"y","les":"m","ud":"n","ism":"n","age":"m","mat":"m","ast":"y","nal":"m",
"par":"m","ish":"y","gu":"y","lis":"m","rea":"m","mis":"m","dr":"y","rin":"m","fr":"y",
"imp":"m","nu":"m","den":"m","tur":"m","ure":"m","we":"y","act":"m","for":"m","tal":"m",
"nk":"y","gh":"n","wi":"y","sl":"y","ass":"y","tro":"m","gen":"m","gn":"n","cha":"y",
"hu":"m","one":"m","ret":"m","oun":"m","ven":"m","ain":"y","nge":"m","wo":"m","omp":"n",
"rp":"n","pos":"m","tar":"m","spe":"y","rep":"m","pen":"y","af":"m","app":"m","comp":"m",
"ple":"m","pla":"y","ld":"m","cor":"m","car":"y","ny":"m","pri":"m","mar":"y","len":"m",
"iss":"m","rop":"m","col":"m","cont":"m","fy":"n","att":"m","inf":"m","sur":"m","cou":"m",
"fer":"m","din":"m","lea":"y","des":"m","arr":"m","rem":"m","sce":"m","nse":"m","rk":"m",
"rab":"m","hor":"m","gat":"m","exp":"m","cri":"m","cra":"y","cle":"m","sk":"m","scr":"m",
"rel":"m","arc":"m","ach":"y","ace":"y","ram":"m","orm":"m","ther":"m","sol":"m","of":"m",
"acc":"m","wh":"y","tch":"m","dg":"m","til":"m","sw":"y","pli":"m","sis":"m","erv":"n",
"ref":"m","emp":"m","cho":"m","rse":"m","py":"m","mit":"m","ify":"n","ict":"m","cent":"m",
"son":"m","dem":"m","comm":"m","uct":"n","ton":"m","rev":"m","hin":"m","ept":"n","bar":"y",
"sup":"m","net":"m","ky":"m","gle":"m","reg":"m","sor":"m","nci":"n","duc":"m","las":"m",
"rge":"m","ft":"m","conc":"m","vel":"m","ude":"m","rad":"m","ext":"m","lor":"m","ium":"n",
"nes":"n","gin":"m","gar":"y","dge":"m","dep":"m","aut":"m","uit":"m","uff":"m","sma":"m",
"sem":"m","gan":"m","spec":"m","ode":"m","mul":"m","def":"m","stri":"m","rus":"m","rom":"m",
"nor":"m","vit":"m","try":"m","tel":"m","sec":"m","esp":"n","emb":"m","alt":"m","rf":"n",
"phy":"m","som":"m","ship":"m","rog":"m","rid":"m","isp":"m","hon":"m","ctor":"m","wn":"m",
"vent":"m","sho":"y","sat":"m","lon":"m","vat":"n","ung":"m","stru":"m","pic":"m","med":"m",
"lut":"n","lim":"m","lc":"n","gic":"m","cap":"y","bor":"m","arch":"m","amb":"m","rov":"n",
"rip":"m","lum":"m","lm":"m","evi":"m","eth":"m","cru":"m","ward":"m","tant":"m","rum":"m",
"ras":"n","pha":"m","ox":"y","une":"m","ule":"m","pon":"m","hes":"n","bur":"m",
}

gold={r[0] for r in csv.reader(open(SRC2)) if len(r)>2 and r[2].strip()}
rows=list(csv.reader(open(C3)))
changed=skipped_gold=0
for r in rows[1:]:
    g=r[0]
    if g in OV:
        if g in gold:
            skipped_gold+=1; continue
        if r[2]!=OV[g]:
            r[2]=OV[g]; changed+=1
        else:
            r[2]=OV[g]
csv.writer(open(C3,"w",newline="")).writerows(rows)
# report distribution + how many overrides differ from gold-style
dist={}
for r in rows[1:]: dist[r[2]]=dist.get(r[2],0)+1
print(f"applied overrides; strong changed on {changed} rows; {skipped_gold} gold grams skipped")
print("strong distribution now:", dist)
