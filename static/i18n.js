/* Customer-screen languages: English, Hindi, Kannada. The customer picks one from the top bar (remembered in this browser).
   T(s, vars) translates a fixed English string; TF(msg) translates a message the server wrote (validation errors,
   notifications) by pattern. Both return the English text unchanged for staff, for English, and for anything unknown, so a
   missing entry shows English rather than nothing. Form values sent to the server always stay in English. */
let LANG=(()=>{try{return localStorage.getItem('aletheia_lang')||'en'}catch(e){return 'en'}})();
const LANGS=[['en','English'],['hi','हिन्दी'],['kn','ಕನ್ನಡ']];
(()=>{const l=document.createElement('link');l.rel='stylesheet';l.href='https://fonts.googleapis.com/css2?family=Noto+Sans+Devanagari:wght@400;500;600;700&family=Noto+Sans+Kannada:wght@400;500;600;700&display=swap';document.head.append(l);
 const s=document.createElement('style');s.textContent=`
html[lang=hi] body{font-family:Inter,"Noto Sans Devanagari","Nirmala UI",ui-sans-serif,system-ui,sans-serif}
html[lang=kn] body{font-family:Inter,"Noto Sans Kannada","Nirmala UI",ui-sans-serif,system-ui,sans-serif}
.lsw{display:flex;align-items:center;gap:6px;flex-shrink:0}.lsw svg{color:var(--mu)}
.lsw select{height:auto!important;width:auto;padding:7px 28px 7px 10px;border-radius:12px;border:1px solid var(--ln);background:var(--cd);font-weight:600;color:var(--tx);cursor:pointer}`;document.head.append(s)})();

/* [English, Hindi, Kannada] */
const I18N=[
/* shell */
['Open requests','खुले अनुरोध','ತೆರೆದ ವಿನಂತಿಗಳು'],['Tickets','टिकट','ಟಿಕೆಟ್‌ಗಳು'],['Notifications','सूचनाएँ','ಅಧಿಸೂಚನೆಗಳು'],
['Language','भाषा','ಭಾಷೆ'],['Short Circuit Laboratory','शॉर्ट सर्किट प्रयोगशाला','ಶಾರ್ಟ್ ಸರ್ಕ್ಯೂಟ್ ಪ್ರಯೋಗಾಲಯ'],
['Central Power Research Institute','केंद्रीय विद्युत अनुसंधान संस्थान','ಕೇಂದ್ರ ವಿದ್ಯುತ್ ಸಂಶೋಧನಾ ಸಂಸ್ಥೆ'],
['Central Power Research Institute, Bengaluru','केंद्रीय विद्युत अनुसंधान संस्थान, बेंगलुरु','ಕೇಂದ್ರ ವಿದ್ಯುತ್ ಸಂಶೋಧನಾ ಸಂಸ್ಥೆ, ಬೆಂಗಳೂರು'],
['Ministry of Power, Govt. of India','विद्युत मंत्रालय, भारत सरकार','ವಿದ್ಯುತ್ ಸಚಿವಾಲಯ, ಭಾರತ ಸರ್ಕಾರ'],
['System online','सिस्टम ऑनलाइन','ವ್ಯವಸ್ಥೆ ಆನ್‌ಲೈನ್'],['Rule-based checks (IS 1180 references)','नियम-आधारित जाँच (IS 1180 संदर्भ)','ನಿಯಮ-ಆಧಾರಿತ ಪರಿಶೀಲನೆಗಳು (IS 1180 ಉಲ್ಲೇಖಗಳು)'],
['Your session has ended. Sign in again.','आपका सत्र समाप्त हो गया है। फिर से साइन इन करें।','ನಿಮ್ಮ ಅವಧಿ ಮುಗಿದಿದೆ. ಮತ್ತೆ ಸೈನ್ ಇನ್ ಮಾಡಿ.'],
['Change your password first','पहले अपना पासवर्ड बदलें','ಮೊದಲು ನಿಮ್ಮ ಪಾಸ್‌ವರ್ಡ್ ಬದಲಾಯಿಸಿ'],
/* user menu and password */
['Customer','ग्राहक','ಗ್ರಾಹಕ'],['Tester','परीक्षक','ಪರೀಕ್ಷಕ'],['Admin','व्यवस्थापक','ನಿರ್ವಾಹಕ'],['View as','इस रूप में देखें','ಹೀಗೆ ವೀಕ್ಷಿಸಿ'],
['Change password','पासवर्ड बदलें','ಪಾಸ್‌ವರ್ಡ್ ಬದಲಾಯಿಸಿ'],['Sign out','साइन आउट','ಸೈನ್ ಔಟ್'],['Change your password','अपना पासवर्ड बदलें','ನಿಮ್ಮ ಪಾಸ್‌ವರ್ಡ್ ಬದಲಾಯಿಸಿ'],
['Current password','वर्तमान पासवर्ड','ಪ್ರಸ್ತುತ ಪಾಸ್‌ವರ್ಡ್'],['New password (10 characters or more)','नया पासवर्ड (10 या अधिक अक्षर)','ಹೊಸ ಪಾಸ್‌ವರ್ಡ್ (10 ಅಥವಾ ಹೆಚ್ಚು ಅಕ್ಷರಗಳು)'],
['New password again','नया पासवर्ड फिर से','ಹೊಸ ಪಾಸ್‌ವರ್ಡ್ ಮತ್ತೊಮ್ಮೆ'],['Cancel','रद्द करें','ರದ್ದುಮಾಡಿ'],
['The two new passwords differ','दोनों नए पासवर्ड अलग हैं','ಎರಡು ಹೊಸ ಪಾಸ್‌ವರ್ಡ್‌ಗಳು ಹೊಂದಾಣಿಕೆಯಾಗುತ್ತಿಲ್ಲ'],['Password changed','पासवर्ड बदल दिया गया','ಪಾಸ್‌ವರ್ಡ್ ಬದಲಾಯಿಸಲಾಗಿದೆ'],
['This is a temporary password. Choose your own before you continue.','यह एक अस्थायी पासवर्ड है। आगे बढ़ने से पहले अपना पासवर्ड चुनें।','ಇದು ತಾತ್ಕಾಲಿಕ ಪಾಸ್‌ವರ್ಡ್. ಮುಂದುವರಿಯುವ ಮೊದಲು ನಿಮ್ಮದೇ ಪಾಸ್‌ವರ್ಡ್ ಆಯ್ಕೆಮಾಡಿ.'],
['Choose a new password','नया पासवर्ड चुनें','ಹೊಸ ಪಾಸ್‌ವರ್ಡ್ ಆಯ್ಕೆಮಾಡಿ'],
/* my jobs */
['Test jobs for {org} at the CPRI Short Circuit Laboratory','CPRI शॉर्ट सर्किट प्रयोगशाला में {org} के परीक्षण कार्य','CPRI ಶಾರ್ಟ್ ಸರ್ಕ್ಯೂಟ್ ಪ್ರಯೋಗಾಲಯದಲ್ಲಿ {org} ಸಂಸ್ಥೆಯ ಪರೀಕ್ಷಾ ಕಾರ್ಯಗಳು'],
['your organisation','आपका संगठन','ನಿಮ್ಮ ಸಂಸ್ಥೆ'],['New test request','नया परीक्षण अनुरोध','ಹೊಸ ಪರೀಕ್ಷಾ ವಿನಂತಿ'],
['Sample {s}','नमूना {s}','ಮಾದರಿ {s}'],['received {d}','प्राप्त {d}','ಸ್ವೀಕರಿಸಿದ್ದು {d}'],
['Report released','रिपोर्ट जारी','ವರದಿ ಬಿಡುಗಡೆಯಾಗಿದೆ'],['In progress','प्रगति पर','ಪ್ರಗತಿಯಲ್ಲಿದೆ'],['No jobs yet','अभी कोई कार्य नहीं','ಇನ್ನೂ ಯಾವುದೇ ಕಾರ್ಯಗಳಿಲ್ಲ'],
['Jobs appear here once the laboratory registers your product.','प्रयोगशाला द्वारा आपका उत्पाद पंजीकृत होते ही कार्य यहाँ दिखाई देंगे।','ಪ್ರಯೋಗಾಲಯವು ನಿಮ್ಮ ಉತ್ಪನ್ನವನ್ನು ನೋಂದಾಯಿಸಿದ ನಂತರ ಕಾರ್ಯಗಳು ಇಲ್ಲಿ ಕಾಣಿಸುತ್ತವೆ.'],
['Raise a ticket','टिकट दर्ज करें','ಟಿಕೆಟ್ ಸಲ್ಲಿಸಿ'],['Download final report','अंतिम रिपोर्ट डाउनलोड करें','ಅಂತಿಮ ವರದಿಯನ್ನು ಡೌನ್‌ಲೋಡ್ ಮಾಡಿ'],
['Progress','प्रगति','ಪ್ರಗತಿ'],['{a} of {b} tests approved','{b} में से {a} परीक्षण स्वीकृत','{b} ರಲ್ಲಿ {a} ಪರೀಕ್ಷೆಗಳು ಅನುಮೋದಿತ'],
['{n} pending verification','{n} सत्यापन हेतु लंबित','{n} ಪರಿಶೀಲನೆಗೆ ಬಾಕಿ'],['{n} not started','{n} शुरू नहीं हुए','{n} ಪ್ರಾರಂಭವಾಗಿಲ್ಲ'],
['Not started','शुरू नहीं हुआ','ಪ್ರಾರಂಭವಾಗಿಲ್ಲ'],['Received','प्राप्त','ಸ್ವೀಕರಿಸಲಾಗಿದೆ'],['Pending verification','सत्यापन लंबित','ಪರಿಶೀಲನೆ ಬಾಕಿ'],
['Being corrected','सुधार जारी','ತಿದ್ದುಪಡಿ ನಡೆಯುತ್ತಿದೆ'],['Approved','स्वीकृत','ಅನುಮೋದಿತ'],['Not applicable','लागू नहीं','ಅನ್ವಯಿಸುವುದಿಲ್ಲ'],
['Values are shown only for tests the laboratory has approved, so you never see a figure that may still be corrected.','मान केवल उन परीक्षणों के दिखाए जाते हैं जिन्हें प्रयोगशाला ने स्वीकृत किया है, ताकि आपको ऐसा कोई आँकड़ा न दिखे जिसमें अभी सुधार हो सकता है।','ಪ್ರಯೋಗಾಲಯ ಅನುಮೋದಿಸಿದ ಪರೀಕ್ಷೆಗಳ ಮೌಲ್ಯಗಳನ್ನು ಮಾತ್ರ ತೋರಿಸಲಾಗುತ್ತದೆ; ಹೀಗಾಗಿ ಇನ್ನೂ ತಿದ್ದುಪಡಿಯಾಗಬಹುದಾದ ಯಾವುದೇ ಅಂಕಿ ನಿಮಗೆ ಕಾಣಿಸುವುದಿಲ್ಲ.'],
['Correction in progress','सुधार प्रगति पर','ತಿದ್ದುಪಡಿ ಪ್ರಗತಿಯಲ್ಲಿದೆ'],
['The laboratory is correcting the released report:','प्रयोगशाला जारी रिपोर्ट में सुधार कर रही है:','ಪ್ರಯೋಗಾಲಯವು ಬಿಡುಗಡೆಯಾದ ವರದಿಯನ್ನು ತಿದ್ದುಪಡಿ ಮಾಡುತ್ತಿದೆ:'],
['The released version below stays valid until the corrected version is released.','सुधारा गया संस्करण जारी होने तक नीचे दिया गया जारी संस्करण मान्य रहेगा।','ತಿದ್ದುಪಡಿ ಮಾಡಿದ ಆವೃತ್ತಿ ಬಿಡುಗಡೆಯಾಗುವವರೆಗೆ ಕೆಳಗಿನ ಬಿಡುಗಡೆಯಾದ ಆವೃತ್ತಿ ಮಾನ್ಯವಾಗಿರುತ್ತದೆ.'],
['Final report','अंतिम रिपोर्ट','ಅಂತಿಮ ವರದಿ'],['Version {v}, released {at}','संस्करण {v}, जारी {at}','ಆವೃತ್ತಿ {v}, ಬಿಡುಗಡೆ {at}'],['Result','परिणाम','ಫಲಿತಾಂಶ'],
['Complies','अनुरूप है','ಅನುಸರಿಸುತ್ತದೆ'],['Does not comply','अनुरूप नहीं है','ಅನುಸರಿಸುವುದಿಲ್ಲ'],['Complies (partly evaluated)','अनुरूप है (आंशिक रूप से मूल्यांकित)','ಅನುಸರಿಸುತ್ತದೆ (ಭಾಗಶಃ ಮೌಲ್ಯಮಾಪನ)'],
['Fingerprint (SHA-256)','फिंगरप्रिंट (SHA-256)','ಫಿಂಗರ್‌ಪ್ರಿಂಟ್ (SHA-256)'],['Open the verification page','सत्यापन पृष्ठ खोलें','ಪರಿಶೀಲನಾ ಪುಟವನ್ನು ತೆರೆಯಿರಿ'],
['Earlier versions','पिछले संस्करण','ಹಿಂದಿನ ಆವೃತ್ತಿಗಳು'],['Superseded','प्रतिस्थापित','ಬದಲಾಯಿಸಲಾಗಿದೆ'],['Download','डाउनलोड','ಡೌನ್‌ಲೋಡ್'],
['Partial report','आंशिक रिपोर्ट','ಭಾಗಶಃ ವರದಿ'],['Download partial report (PDF)','आंशिक रिपोर्ट डाउनलोड करें (PDF)','ಭಾಗಶಃ ವರದಿಯನ್ನು ಡೌನ್‌ಲೋಡ್ ಮಾಡಿ (PDF)'],
['Built from the approved tests only; marked PARTIAL, NOT FINAL. Version {v} of {at}, fingerprint','केवल स्वीकृत परीक्षणों से बनी; "PARTIAL, NOT FINAL" (आंशिक, अंतिम नहीं) चिह्नित। संस्करण {v}, {at}, फिंगरप्रिंट','ಅನುಮೋದಿತ ಪರೀಕ್ಷೆಗಳಿಂದ ಮಾತ್ರ ರಚಿಸಲಾಗಿದೆ; "PARTIAL, NOT FINAL" (ಭಾಗಶಃ, ಅಂತಿಮವಲ್ಲ) ಎಂದು ಗುರುತಿಸಲಾಗಿದೆ. ಆವೃತ್ತಿ {v}, {at}, ಫಿಂಗರ್‌ಪ್ರಿಂಟ್'],
['Earlier:','पहले के:','ಹಿಂದಿನವು:'],['Approved values','स्वीकृत मान','ಅನುಮೋದಿತ ಮೌಲ್ಯಗಳು'],
/* notifications */
['Request returned to you','अनुरोध आपको लौटाया गया','ವಿನಂತಿಯನ್ನು ನಿಮಗೆ ಹಿಂತಿರುಗಿಸಲಾಗಿದೆ'],['Request received','अनुरोध प्राप्त हुआ','ವಿನಂತಿ ಸ್ವೀಕರಿಸಲಾಗಿದೆ'],
['Your test report is ready','आपकी परीक्षण रिपोर्ट तैयार है','ನಿಮ್ಮ ಪರೀಕ್ಷಾ ವರದಿ ಸಿದ್ಧವಾಗಿದೆ'],['Notice','सूचना','ಸೂಚನೆ'],['{n} updates','{n} अपडेट','{n} ನವೀಕರಣಗಳು'],
['{n} unread','{n} अपठित','{n} ಓದದಿರುವವು'],['Nothing unread.','कुछ भी अपठित नहीं।','ಓದದಿರುವುದು ಏನೂ ಇಲ್ಲ.'],
['View all notifications','सभी सूचनाएँ देखें','ಎಲ್ಲಾ ಅಧಿಸೂಚನೆಗಳನ್ನು ನೋಡಿ'],['Loading…','लोड हो रहा है…','ಲೋಡ್ ಆಗುತ್ತಿದೆ…'],
['{n} unread. Click a notification to open what it is about.','{n} अपठित। जिस विषय की सूचना है, उसे खोलने के लिए सूचना पर क्लिक करें।','{n} ಓದದಿರುವವು. ಅಧಿಸೂಚನೆಯ ವಿಷಯವನ್ನು ತೆರೆಯಲು ಅದರ ಮೇಲೆ ಕ್ಲಿಕ್ ಮಾಡಿ.'],
['Mark all as read','सभी को पढ़ा हुआ चिह्नित करें','ಎಲ್ಲವನ್ನೂ ಓದಿದೆ ಎಂದು ಗುರುತಿಸಿ'],['Unread','अपठित','ಓದದಿರುವವು'],['Needs action','कार्रवाई आवश्यक','ಕ್ರಮ ಅಗತ್ಯ'],['All','सभी','ಎಲ್ಲಾ'],
['Needs your action','आपकी कार्रवाई आवश्यक','ನಿಮ್ಮ ಕ್ರಮ ಅಗತ್ಯ'],['For information','जानकारी के लिए','ಮಾಹಿತಿಗಾಗಿ'],['All notifications','सभी सूचनाएँ','ಎಲ್ಲಾ ಅಧಿಸೂಚನೆಗಳು'],
['Today','आज','ಇಂದು'],['Yesterday','कल','ನಿನ್ನೆ'],['Earlier','पहले','ಹಿಂದಿನವು'],
['Nothing needs your action.','किसी चीज़ पर आपकी कार्रवाई आवश्यक नहीं है।','ಯಾವುದಕ್ಕೂ ನಿಮ್ಮ ಕ್ರಮ ಅಗತ್ಯವಿಲ್ಲ.'],['No notifications yet.','अभी कोई सूचना नहीं।','ಇನ್ನೂ ಯಾವುದೇ ಅಧಿಸೂಚನೆಗಳಿಲ್ಲ.'],
['Your test request was received by the laboratory','आपका परीक्षण अनुरोध प्रयोगशाला को प्राप्त हो गया है','ನಿಮ್ಮ ಪರೀಕ್ಷಾ ವಿನಂತಿಯನ್ನು ಪ್ರಯೋಗಾಲಯ ಸ್ವೀಕರಿಸಿದೆ'],
/* request form: page */
['Waiting for the laboratory','प्रयोगशाला की प्रतीक्षा में','ಪ್ರಯೋಗಾಲಯಕ್ಕಾಗಿ ಕಾಯಲಾಗುತ್ತಿದೆ'],['Returned to you for correction','सुधार के लिए आपको लौटाया गया','ತಿದ್ದುಪಡಿಗಾಗಿ ನಿಮಗೆ ಹಿಂತಿರುಗಿಸಲಾಗಿದೆ'],
['Received by the laboratory','प्रयोगशाला द्वारा प्राप्त','ಪ್ರಯೋಗಾಲಯ ಸ್ವೀಕರಿಸಿದೆ'],['Replaced by a corrected request','सुधारे गए अनुरोध से प्रतिस्थापित','ತಿದ್ದುಪಡಿ ಮಾಡಿದ ವಿನಂತಿಯಿಂದ ಬದಲಾಯಿಸಲಾಗಿದೆ'],
['CENTRAL POWER RESEARCH INSTITUTE','केंद्रीय विद्युत अनुसंधान संस्थान','ಕೇಂದ್ರ ವಿದ್ಯುತ್ ಸಂಶೋಧನಾ ಸಂಸ್ಥೆ'],
['Name of the Unit / Division: SHORT CIRCUIT LABORATORY','इकाई / प्रभाग का नाम: शॉर्ट सर्किट प्रयोगशाला','ಘಟಕ / ವಿಭಾಗದ ಹೆಸರು: ಶಾರ್ಟ್ ಸರ್ಕ್ಯೂಟ್ ಪ್ರಯೋಗಾಲಯ'],
['Format No:','प्रारूप सं.:','ನಮೂನೆ ಸಂ.:'],['Issue No. 02','निर्गम सं. 02','ಪ್ರಕಟಣೆ ಸಂ. 02'],['Date of Issue: 22-06-2022','निर्गम तिथि: 22-06-2022','ಪ್ರಕಟಣೆಯ ದಿನಾಂಕ: 22-06-2022'],
['Customer Request Form','ग्राहक अनुरोध प्रपत्र','ಗ್ರಾಹಕ ವಿನಂತಿ ನಮೂನೆ'],['(To be filled by the laboratory)','(प्रयोगशाला द्वारा भरा जाए)','(ಪ್ರಯೋಗಾಲಯವು ಭರ್ತಿ ಮಾಡಬೇಕು)'],
['Sheet {n} of 3','पत्रक {n} / 3','ಹಾಳೆ {n} / 3'],['Required','आवश्यक','ಅಗತ್ಯ'],['Choose...','चुनें...','ಆರಿಸಿ...'],['Yes','हाँ','ಹೌದು'],['No','नहीं','ಇಲ್ಲ'],
['Reason it does not apply','लागू न होने का कारण','ಅನ್ವಯಿಸದಿರುವ ಕಾರಣ'],
['Correct and send again','सुधारें और फिर से भेजें','ತಿದ್ದುಪಡಿ ಮಾಡಿ ಮತ್ತೆ ಕಳುಹಿಸಿ'],['Returned by the laboratory:','प्रयोगशाला द्वारा लौटाया गया:','ಪ್ರಯೋಗಾಲಯ ಹಿಂತಿರುಗಿಸಿದೆ:'],
['Customer Request Form {fmt}, filled in online for {org}. Every value is checked as you type; the laboratory receives it and records the rest when the sample arrives.','ग्राहक अनुरोध प्रपत्र {fmt}, {org} के लिए ऑनलाइन भरा गया। टाइप करते ही हर मान की जाँच होती है; प्रयोगशाला इसे प्राप्त करती है और नमूना पहुँचने पर शेष विवरण दर्ज करती है।','ಗ್ರಾಹಕ ವಿನಂತಿ ನಮೂನೆ {fmt}, {org} ಗಾಗಿ ಆನ್‌ಲೈನ್‌ನಲ್ಲಿ ಭರ್ತಿ ಮಾಡಲಾಗಿದೆ. ನೀವು ಟೈಪ್ ಮಾಡುತ್ತಿದ್ದಂತೆ ಪ್ರತಿ ಮೌಲ್ಯವನ್ನು ಪರಿಶೀಲಿಸಲಾಗುತ್ತದೆ; ಪ್ರಯೋಗಾಲಯವು ಇದನ್ನು ಸ್ವೀಕರಿಸಿ, ಮಾದರಿ ಬಂದಾಗ ಉಳಿದ ವಿವರಗಳನ್ನು ದಾಖಲಿಸುತ್ತದೆ.'],
['Tests to be carried out','किए जाने वाले परीक्षण','ನಡೆಸಬೇಕಾದ ಪರೀಕ್ಷೆಗಳು'],
['Tick each test you need; the laboratory plans the job from these.','आपको जिन परीक्षणों की आवश्यकता है, उन पर टिक करें; प्रयोगशाला इन्हीं के आधार पर कार्य की योजना बनाती है।','ನಿಮಗೆ ಬೇಕಾದ ಪ್ರತಿಯೊಂದು ಪರೀಕ್ಷೆಯನ್ನು ಗುರುತಿಸಿ; ಇವುಗಳ ಆಧಾರದ ಮೇಲೆ ಪ್ರಯೋಗಾಲಯವು ಕಾರ್ಯವನ್ನು ಯೋಜಿಸುತ್ತದೆ.'],
['Customers Name & Signature with Date','ग्राहक का नाम व हस्ताक्षर, दिनांक सहित','ಗ್ರಾಹಕರ ಹೆಸರು ಮತ್ತು ಸಹಿ, ದಿನಾಂಕದೊಂದಿಗೆ'],
["Physical condition of the sample on receipt, the laboratory's capability and the acceptance of the job are recorded by the laboratory when your sample arrives.",'प्राप्ति पर नमूने की भौतिक स्थिति, प्रयोगशाला की क्षमता और कार्य की स्वीकृति आपका नमूना पहुँचने पर प्रयोगशाला द्वारा दर्ज की जाती है।','ಸ್ವೀಕರಿಸಿದಾಗ ಮಾದರಿಯ ಭೌತಿಕ ಸ್ಥಿತಿ, ಪ್ರಯೋಗಾಲಯದ ಸಾಮರ್ಥ್ಯ ಮತ್ತು ಕಾರ್ಯದ ಅಂಗೀಕಾರವನ್ನು ನಿಮ್ಮ ಮಾದರಿ ಬಂದಾಗ ಪ್ರಯೋಗಾಲಯವು ದಾಖಲಿಸುತ್ತದೆ.'],
['Check for problems','समस्याओं की जाँच करें','ಸಮಸ್ಯೆಗಳಿಗಾಗಿ ಪರಿಶೀಲಿಸಿ'],['Send the corrected request','सुधारा गया अनुरोध भेजें','ತಿದ್ದುಪಡಿ ಮಾಡಿದ ವಿನಂತಿಯನ್ನು ಕಳುಹಿಸಿ'],
['Send the request','अनुरोध भेजें','ವಿನಂತಿಯನ್ನು ಕಳುಹಿಸಿ'],['Everything is filled in correctly.','सब कुछ सही भरा गया है।','ಎಲ್ಲವನ್ನೂ ಸರಿಯಾಗಿ ಭರ್ತಿ ಮಾಡಲಾಗಿದೆ.'],
['Request sent to the laboratory','अनुरोध प्रयोगशाला को भेजा गया','ವಿನಂತಿಯನ್ನು ಪ್ರಯೋಗಾಲಯಕ್ಕೆ ಕಳುಹಿಸಲಾಗಿದೆ'],
['1 thing to correct','1 सुधार आवश्यक','1 ತಿದ್ದುಪಡಿ ಅಗತ್ಯ'],['{n} things to correct','{n} सुधार आवश्यक','{n} ತಿದ್ದುಪಡಿಗಳು ಅಗತ್ಯ'],['Please check','कृपया जाँचें','ದಯವಿಟ್ಟು ಪರಿಶೀಲಿಸಿ'],
['Test requests','परीक्षण अनुरोध','ಪರೀಕ್ಷಾ ವಿನಂತಿಗಳು'],
['Fill in the Customer Request Form online; the laboratory receives it and opens the job when your sample arrives.','ग्राहक अनुरोध प्रपत्र ऑनलाइन भरें; प्रयोगशाला इसे प्राप्त करती है और आपका नमूना पहुँचने पर कार्य खोलती है।','ಗ್ರಾಹಕ ವಿನಂತಿ ನಮೂನೆಯನ್ನು ಆನ್‌ಲೈನ್‌ನಲ್ಲಿ ಭರ್ತಿ ಮಾಡಿ; ಪ್ರಯೋಗಾಲಯವು ಅದನ್ನು ಸ್ವೀಕರಿಸಿ, ನಿಮ್ಮ ಮಾದರಿ ಬಂದಾಗ ಕಾರ್ಯವನ್ನು ತೆರೆಯುತ್ತದೆ.'],
['Request {id}','अनुरोध {id}','ವಿನಂತಿ {id}'],['sent {at}','भेजा गया {at}','ಕಳುಹಿಸಿದ್ದು {at}'],['Reason:','कारण:','ಕಾರಣ:'],['Job {s}','कार्य {s}','ಕಾರ್ಯ {s}'],
['No requests yet.','अभी कोई अनुरोध नहीं।','ಇನ್ನೂ ಯಾವುದೇ ವಿನಂತಿಗಳಿಲ್ಲ.'],
/* request form: fields (workflow.py REQUEST_FIELDS) */
['Name and Address of the Customer','ग्राहक का नाम और पता','ಗ್ರಾಹಕರ ಹೆಸರು ಮತ್ತು ವಿಳಾಸ'],['Sample storage / Handling / Disposal','नमूना भंडारण / रखरखाव / निपटान','ಮಾದರಿ ಸಂಗ್ರಹಣೆ / ನಿರ್ವಹಣೆ / ವಿಲೇವಾರಿ'],
['Name of the witnessing persons','साक्षी व्यक्तियों के नाम','ಸಾಕ್ಷಿ ವ್ಯಕ್ತಿಗಳ ಹೆಸರುಗಳು'],['Name of the Customer','ग्राहक का नाम','ಗ್ರಾಹಕರ ಹೆಸರು'],
['Address (street, area)','पता (सड़क, क्षेत्र)','ವಿಳಾಸ (ರಸ್ತೆ, ಪ್ರದೇಶ)'],['City / town','शहर / कस्बा','ನಗರ / ಪಟ್ಟಣ'],['State / union territory','राज्य / केंद्र शासित प्रदेश','ರಾಜ್ಯ / ಕೇಂದ್ರಾಡಳಿತ ಪ್ರದೇಶ'],
['PIN code','पिन कोड','ಪಿನ್ ಕೋಡ್'],['Contact person','संपर्क व्यक्ति','ಸಂಪರ್ಕ ವ್ಯಕ್ತಿ'],['Phone','फ़ोन','ದೂರವಾಣಿ'],['Email (for notifications)','ईमेल (सूचनाओं के लिए)','ಇಮೇಲ್ (ಅಧಿಸೂಚನೆಗಳಿಗಾಗಿ)'],
['Sample(s) to be tested','परीक्षण हेतु नमूना/नमूने','ಪರೀಕ್ಷಿಸಬೇಕಾದ ಮಾದರಿ(ಗಳು)'],['Rating of the sample(s) to be tested','परीक्षण हेतु नमूने/नमूनों की रेटिंग','ಪರೀಕ್ಷಿಸಬೇಕಾದ ಮಾದರಿ(ಗಳ) ರೇಟಿಂಗ್'],
['Description of the test sample(s)','परीक्षण नमूने/नमूनों का विवरण','ಪರೀಕ್ಷಾ ಮಾದರಿ(ಗಳ) ವಿವರಣೆ'],['Type','प्रकार','ಪ್ರಕಾರ'],['Serial Number(s)','क्रम संख्या','ಕ್ರಮ ಸಂಖ್ಯೆ(ಗಳು)'],
["Manufacturer's Details",'निर्माता का विवरण','ತಯಾರಕರ ವಿವರಗಳು'],['Drawing Number(s)','ड्रॉइंग संख्या','ರೇಖಾಚಿತ್ರ ಸಂಖ್ಯೆ(ಗಳು)'],['Customers Requirement','ग्राहक की आवश्यकता','ಗ್ರಾಹಕರ ಅಗತ್ಯ'],
['Criteria for Evaluation (Standard/Specification)','मूल्यांकन के मानदंड (मानक/विनिर्देश)','ಮೌಲ್ಯಮಾಪನದ ಮಾನದಂಡ (ಮಾನಕ/ವಿವರಣೆ)'],['Number of Samples','नमूनों की संख्या','ಮಾದರಿಗಳ ಸಂಖ್ಯೆ'],
['a) Taking back the sample after testing','a) परीक्षण के बाद नमूना वापस लेना','a) ಪರೀಕ್ಷೆಯ ನಂತರ ಮಾದರಿಯನ್ನು ಹಿಂಪಡೆಯುವುದು'],
['b) Will not take back the sample, CPRI can scrap and dispose it off','b) नमूना वापस नहीं लेंगे, CPRI इसे स्क्रैप करके निपटा सकता है','b) ಮಾದರಿಯನ್ನು ಹಿಂಪಡೆಯುವುದಿಲ್ಲ, CPRI ಅದನ್ನು ಗುಜರಿ ಮಾಡಿ ವಿಲೇವಾರಿ ಮಾಡಬಹುದು'],
['If samples are not collected as in (a) within 15 days from the date of testing it will be automatically scrapped.','यदि (a) के अनुसार परीक्षण की तिथि से 15 दिनों के भीतर नमूने नहीं ले जाए गए, तो वे स्वतः स्क्रैप कर दिए जाएँगे।','ಪರೀಕ್ಷೆಯ ದಿನಾಂಕದಿಂದ 15 ದಿನಗಳೊಳಗೆ (a) ಯಂತೆ ಮಾದರಿಗಳನ್ನು ಸಂಗ್ರಹಿಸದಿದ್ದರೆ, ಅವುಗಳನ್ನು ಸ್ವಯಂಚಾಲಿತವಾಗಿ ಗುಜರಿ ಮಾಡಲಾಗುತ್ತದೆ.'],
['Details of test(s) requested','अनुरोधित परीक्षण/परीक्षणों का विवरण','ವಿನಂತಿಸಿದ ಪರೀಕ್ಷೆ(ಗಳ) ವಿವರಗಳು'],
['Specific instructions (if any) for mounting and connection','माउंटिंग और कनेक्शन के लिए विशेष निर्देश (यदि कोई हो)','ಅಳವಡಿಕೆ ಮತ್ತು ಸಂಪರ್ಕಕ್ಕಾಗಿ ನಿರ್ದಿಷ್ಟ ಸೂಚನೆಗಳು (ಇದ್ದರೆ)'],
['Customers Representative','ग्राहक का प्रतिनिधि','ಗ್ರಾಹಕರ ಪ್ರತಿನಿಧಿ'],['Other than Customer','ग्राहक के अतिरिक्त','ಗ್ರಾಹಕರನ್ನು ಹೊರತುಪಡಿಸಿ'],
['Test Report to be despatched to','परीक्षण रिपोर्ट किसे भेजी जाए','ಪರೀಕ್ಷಾ ವರದಿಯನ್ನು ಯಾರಿಗೆ ಕಳುಹಿಸಬೇಕು'],['Test report Despatch mode','परीक्षण रिपोर्ट भेजने का माध्यम','ಪರೀಕ್ಷಾ ವರದಿ ಕಳುಹಿಸುವ ವಿಧಾನ'],
['Number of Additional Test Reports (Required / not required)','अतिरिक्त परीक्षण रिपोर्टों की संख्या (आवश्यक / आवश्यक नहीं)','ಹೆಚ್ಚುವರಿ ಪರೀಕ್ಷಾ ವರದಿಗಳ ಸಂಖ್ಯೆ (ಅಗತ್ಯ / ಅಗತ್ಯವಿಲ್ಲ)'],
['MSME Discount','MSME छूट','MSME ರಿಯಾಯಿತಿ'],['Applicable','लागू','ಅನ್ವಯಿಸುತ್ತದೆ'],['Not Applicable','लागू नहीं','ಅನ್ವಯಿಸುವುದಿಲ್ಲ'],
['If applicable, the customer provides the necessary documents before testing. Billing to be done accordingly.','यदि लागू हो, तो ग्राहक परीक्षण से पहले आवश्यक दस्तावेज़ प्रदान करेगा। बिलिंग तदनुसार की जाएगी।','ಅನ್ವಯಿಸಿದರೆ, ಗ್ರಾಹಕರು ಪರೀಕ್ಷೆಗೆ ಮೊದಲು ಅಗತ್ಯ ದಾಖಲೆಗಳನ್ನು ಒದಗಿಸಬೇಕು. ಅದರಂತೆ ಬಿಲ್ಲಿಂಗ್ ಮಾಡಲಾಗುತ್ತದೆ.'],
['Whether statement of conformity is required in the test report','क्या परीक्षण रिपोर्ट में अनुरूपता का विवरण आवश्यक है','ಪರೀಕ್ಷಾ ವರದಿಯಲ್ಲಿ ಅನುಸರಣೆಯ ಹೇಳಿಕೆ ಅಗತ್ಯವಿದೆಯೇ'],
['a) If No, then only the observed results will be reported. b) If Yes, please select any one of (i) OR (ii) OR (iii).','a) यदि नहीं, तो केवल देखे गए परिणाम रिपोर्ट किए जाएँगे। b) यदि हाँ, तो कृपया (i) या (ii) या (iii) में से कोई एक चुनें।','a) ಇಲ್ಲವಾದರೆ, ಗಮನಿಸಿದ ಫಲಿತಾಂಶಗಳನ್ನು ಮಾತ್ರ ವರದಿ ಮಾಡಲಾಗುತ್ತದೆ. b) ಹೌದು ಎಂದಾದರೆ, ದಯವಿಟ್ಟು (i) ಅಥವಾ (ii) ಅಥವಾ (iii) ರಲ್ಲಿ ಯಾವುದಾದರೂ ಒಂದನ್ನು ಆರಿಸಿ.'],
['Decision rule (if Yes)','निर्णय नियम (यदि हाँ)','ನಿರ್ಧಾರ ನಿಯಮ (ಹೌದು ಎಂದಾದರೆ)'],
['(i) Decision on compliance to standard/specification will be based on the requirement mentioned in the standard/specification and measurement uncertainty will be reported (if required) (informed to customer for agreement)','(i) मानक/विनिर्देश के अनुपालन का निर्णय मानक/विनिर्देश में उल्लिखित आवश्यकता के आधार पर होगा और मापन अनिश्चितता रिपोर्ट की जाएगी (यदि आवश्यक हो) (सहमति हेतु ग्राहक को सूचित)','(i) ಮಾನಕ/ವಿವರಣೆಗೆ ಅನುಸರಣೆಯ ನಿರ್ಧಾರವು ಮಾನಕ/ವಿವರಣೆಯಲ್ಲಿ ಉಲ್ಲೇಖಿಸಿದ ಅಗತ್ಯವನ್ನು ಆಧರಿಸಿರುತ್ತದೆ ಮತ್ತು ಮಾಪನ ಅನಿಶ್ಚಿತತೆಯನ್ನು ವರದಿ ಮಾಡಲಾಗುತ್ತದೆ (ಅಗತ್ಯವಿದ್ದರೆ) (ಒಪ್ಪಿಗೆಗಾಗಿ ಗ್ರಾಹಕರಿಗೆ ತಿಳಿಸಲಾಗಿದೆ)'],
['(ii) For the requirement specified by the customer, same will be considered as decision criteria and measurement uncertainty will be reported (if required) (informed to customer for agreement)','(ii) ग्राहक द्वारा निर्दिष्ट आवश्यकता के लिए वही निर्णय मानदंड माना जाएगा और मापन अनिश्चितता रिपोर्ट की जाएगी (यदि आवश्यक हो) (सहमति हेतु ग्राहक को सूचित)','(ii) ಗ್ರಾಹಕರು ನಿರ್ದಿಷ್ಟಪಡಿಸಿದ ಅಗತ್ಯಕ್ಕೆ, ಅದನ್ನೇ ನಿರ್ಧಾರ ಮಾನದಂಡವೆಂದು ಪರಿಗಣಿಸಲಾಗುತ್ತದೆ ಮತ್ತು ಮಾಪನ ಅನಿಶ್ಚಿತತೆಯನ್ನು ವರದಿ ಮಾಡಲಾಗುತ್ತದೆ (ಅಗತ್ಯವಿದ್ದರೆ) (ಒಪ್ಪಿಗೆಗಾಗಿ ಗ್ರಾಹಕರಿಗೆ ತಿಳಿಸಲಾಗಿದೆ)'],
["(iii) If Measurement Uncertainty is to be considered for the decision on compliance for border cases, calculated Measurement Uncertainty at confidence level of approximately 95% (k=2) will be reported and the decision rule for compliance, if MU is subtracted the decision is 'PASS' or MU is added the decision is 'FAIL' (informed to customer for agreement)","(iii) यदि सीमांत मामलों में अनुपालन के निर्णय हेतु मापन अनिश्चितता पर विचार करना हो, तो लगभग 95% (k=2) विश्वास स्तर पर गणना की गई मापन अनिश्चितता रिपोर्ट की जाएगी, और अनुपालन का निर्णय नियम यह होगा: MU घटाने पर निर्णय 'PASS' या MU जोड़ने पर निर्णय 'FAIL' (सहमति हेतु ग्राहक को सूचित)","(iii) ಗಡಿರೇಖೆಯ ಪ್ರಕರಣಗಳಲ್ಲಿ ಅನುಸರಣೆಯ ನಿರ್ಧಾರಕ್ಕೆ ಮಾಪನ ಅನಿಶ್ಚಿತತೆಯನ್ನು ಪರಿಗಣಿಸಬೇಕಾದರೆ, ಸುಮಾರು 95% (k=2) ವಿಶ್ವಾಸ ಮಟ್ಟದಲ್ಲಿ ಲೆಕ್ಕಹಾಕಿದ ಮಾಪನ ಅನಿಶ್ಚಿತತೆಯನ್ನು ವರದಿ ಮಾಡಲಾಗುತ್ತದೆ, ಮತ್ತು ಅನುಸರಣೆಯ ನಿರ್ಧಾರ ನಿಯಮ: MU ಕಳೆದರೆ ನಿರ್ಧಾರ 'PASS' ಅಥವಾ MU ಸೇರಿಸಿದರೆ ನಿರ್ಧಾರ 'FAIL' (ಒಪ್ಪಿಗೆಗಾಗಿ ಗ್ರಾಹಕರಿಗೆ ತಿಳಿಸಲಾಗಿದೆ)"],
['Deviations requested by the customer in the customer requirement shall be above the requirements of the standard/specification and wherever the requirements need to be specified by the customers or not specified in the standard/specification. Deviations requested by the customer shall not impact the integrity of the laboratory or the validity of the results. Decision criteria cannot be changed after the start of the test.','ग्राहक आवश्यकता में ग्राहक द्वारा अनुरोधित विचलन मानक/विनिर्देश की आवश्यकताओं से ऊपर होंगे, और वहाँ लागू होंगे जहाँ आवश्यकताएँ ग्राहक द्वारा निर्दिष्ट की जानी हों या मानक/विनिर्देश में निर्दिष्ट न हों। ग्राहक द्वारा अनुरोधित विचलन प्रयोगशाला की सत्यनिष्ठा या परिणामों की वैधता को प्रभावित नहीं करेंगे। परीक्षण शुरू होने के बाद निर्णय मानदंड बदले नहीं जा सकते।','ಗ್ರಾಹಕರ ಅಗತ್ಯದಲ್ಲಿ ಗ್ರಾಹಕರು ಕೋರಿದ ವಿಚಲನೆಗಳು ಮಾನಕ/ವಿವರಣೆಯ ಅಗತ್ಯಗಳಿಗಿಂತ ಮೇಲ್ಮಟ್ಟದಲ್ಲಿರಬೇಕು, ಮತ್ತು ಅಗತ್ಯಗಳನ್ನು ಗ್ರಾಹಕರು ನಿರ್ದಿಷ್ಟಪಡಿಸಬೇಕಾದಲ್ಲಿ ಅಥವಾ ಮಾನಕ/ವಿವರಣೆಯಲ್ಲಿ ನಿರ್ದಿಷ್ಟಪಡಿಸದಿರುವಲ್ಲಿ ಅನ್ವಯಿಸುತ್ತವೆ. ಗ್ರಾಹಕರು ಕೋರಿದ ವಿಚಲನೆಗಳು ಪ್ರಯೋಗಾಲಯದ ಸಮಗ್ರತೆಯ ಮೇಲೆ ಅಥವಾ ಫಲಿತಾಂಶಗಳ ಸಿಂಧುತ್ವದ ಮೇಲೆ ಪರಿಣಾಮ ಬೀರಬಾರದು. ಪರೀಕ್ಷೆ ಪ್ರಾರಂಭವಾದ ನಂತರ ನಿರ್ಧಾರ ಮಾನದಂಡವನ್ನು ಬದಲಾಯಿಸಲಾಗುವುದಿಲ್ಲ.'],
['I/We guarantee that the sample submitted for the test(s) has been manufactured in accordance with the drawings submitted.','मैं/हम गारंटी देते हैं कि परीक्षण हेतु प्रस्तुत नमूना प्रस्तुत किए गए ड्रॉइंग के अनुसार निर्मित किया गया है।','ಪರೀಕ್ಷೆ(ಗಳಿ)ಗಾಗಿ ಸಲ್ಲಿಸಿದ ಮಾದರಿಯನ್ನು ಸಲ್ಲಿಸಿದ ರೇಖಾಚಿತ್ರಗಳಿಗೆ ಅನುಗುಣವಾಗಿ ತಯಾರಿಸಲಾಗಿದೆ ಎಂದು ನಾನು/ನಾವು ಖಾತರಿಪಡಿಸುತ್ತೇವೆ.'],
['I/We have read & understood the terms and condition for testing at CPRI and agree to the conditions stipulated there in.','मैंने/हमने CPRI में परीक्षण के नियम और शर्तें पढ़ और समझ ली हैं तथा उनमें निर्धारित शर्तों से सहमत हैं।','CPRI ನಲ್ಲಿ ಪರೀಕ್ಷೆಯ ನಿಯಮಗಳು ಮತ್ತು ಷರತ್ತುಗಳನ್ನು ನಾನು/ನಾವು ಓದಿ ಅರ್ಥಮಾಡಿಕೊಂಡಿದ್ದೇವೆ ಮತ್ತು ಅದರಲ್ಲಿ ವಿಧಿಸಿರುವ ಷರತ್ತುಗಳಿಗೆ ಒಪ್ಪುತ್ತೇವೆ.'],
["CPRI Website will publish information on manufacturers' name, products tested, test report number & date of issue and corresponding unique sample code number. The terms & Condition document is made available while making the offer from CPRI for testing; it is also available on www.cpri.in.",'CPRI वेबसाइट पर निर्माताओं का नाम, परीक्षित उत्पाद, परीक्षण रिपोर्ट संख्या व जारी करने की तिथि तथा संबंधित विशिष्ट नमूना कोड संख्या प्रकाशित की जाएगी। नियम व शर्तें दस्तावेज़ CPRI द्वारा परीक्षण का प्रस्ताव देते समय उपलब्ध कराया जाता है; यह www.cpri.in पर भी उपलब्ध है।','CPRI ಜಾಲತಾಣವು ತಯಾರಕರ ಹೆಸರು, ಪರೀಕ್ಷಿಸಿದ ಉತ್ಪನ್ನಗಳು, ಪರೀಕ್ಷಾ ವರದಿ ಸಂಖ್ಯೆ ಮತ್ತು ನೀಡಿದ ದಿನಾಂಕ ಹಾಗೂ ಸಂಬಂಧಿತ ವಿಶಿಷ್ಟ ಮಾದರಿ ಕೋಡ್ ಸಂಖ್ಯೆಯ ಮಾಹಿತಿಯನ್ನು ಪ್ರಕಟಿಸುತ್ತದೆ. ಪರೀಕ್ಷೆಗಾಗಿ CPRI ಪ್ರಸ್ತಾವನೆ ನೀಡುವಾಗ ನಿಯಮಗಳು ಮತ್ತು ಷರತ್ತುಗಳ ದಾಖಲೆಯನ್ನು ಒದಗಿಸಲಾಗುತ್ತದೆ; ಇದು www.cpri.in ನಲ್ಲಿಯೂ ಲಭ್ಯವಿದೆ.'],
['Customers Name (signature)','ग्राहक का नाम (हस्ताक्षर)','ಗ್ರಾಹಕರ ಹೆಸರು (ಸಹಿ)'],['Dated automatically when the request is sent.','अनुरोध भेजे जाने पर तिथि स्वतः अंकित होती है।','ವಿನಂತಿ ಕಳುಹಿಸಿದಾಗ ದಿನಾಂಕವನ್ನು ಸ್ವಯಂಚಾಲಿತವಾಗಿ ನಮೂದಿಸಲಾಗುತ್ತದೆ.'],
['Tests requested','अनुरोधित परीक्षण','ವಿನಂತಿಸಿದ ಪರೀಕ್ಷೆಗಳು'],
/* tests (app.py NAMES) */
['Proforma for Transformers','ट्रांसफॉर्मर हेतु प्रोफ़ॉर्मा','ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್‌ಗಳ ಪ್ರೊಫಾರ್ಮಾ'],['Work Instruction','कार्य निर्देश','ಕಾರ್ಯ ಸೂಚನೆ'],
['Loss Measurement Datasheet','हानि मापन डेटाशीट','ನಷ್ಟ ಮಾಪನ ಡೇಟಾಶೀಟ್'],['Winding Resistance and Loss Logsheet','वाइंडिंग प्रतिरोध और हानि लॉगशीट','ವೈಂಡಿಂಗ್ ಪ್ರತಿರೋಧ ಮತ್ತು ನಷ್ಟ ಲಾಗ್‌ಶೀಟ್'],
['No-Load Loss and Current Logsheet','नो-लोड हानि और धारा लॉगशीट','ನೋ-ಲೋಡ್ ನಷ್ಟ ಮತ್ತು ವಿದ್ಯುತ್ ಪ್ರವಾಹ ಲಾಗ್‌ಶೀಟ್'],['Routine Test Logsheet','नियमित परीक्षण लॉगशीट','ನಿಯತ ಪರೀಕ್ಷಾ ಲಾಗ್‌ಶೀಟ್'],
['Short-Circuit Withstand Test Logsheet','शॉर्ट-सर्किट सहनशीलता परीक्षण लॉगशीट','ಶಾರ್ಟ್-ಸರ್ಕ್ಯೂಟ್ ತಾಳಿಕೆ ಪರೀಕ್ಷಾ ಲಾಗ್‌ಶೀಟ್'],['Temperature-Rise Test Logsheet','तापमान-वृद्धि परीक्षण लॉगशीट','ತಾಪಮಾನ-ಏರಿಕೆ ಪರೀಕ್ಷಾ ಲಾಗ್‌ಶೀಟ್'],
['Pressure and Oil-Leakage Test Logsheet','दबाव और तेल-रिसाव परीक्षण लॉगशीट','ಒತ್ತಡ ಮತ್ತು ತೈಲ-ಸೋರಿಕೆ ಪರೀಕ್ಷಾ ಲಾಗ್‌ಶೀಟ್'],
['Sample Identification Record','नमूना पहचान अभिलेख','ಮಾದರಿ ಗುರುತಿನ ದಾಖಲೆ'],['Supplementary Test Records','पूरक परीक्षण अभिलेख','ಪೂರಕ ಪರೀಕ್ಷಾ ದಾಖಲೆಗಳು'],
/* states and union territories (option labels only; the value sent stays English) */
['Andhra Pradesh','आंध्र प्रदेश','ಆಂಧ್ರ ಪ್ರದೇಶ'],['Arunachal Pradesh','अरुणाचल प्रदेश','ಅರುಣಾಚಲ ಪ್ರದೇಶ'],['Assam','असम','ಅಸ್ಸಾಂ'],['Bihar','बिहार','ಬಿಹಾರ'],
['Chhattisgarh','छत्तीसगढ़','ಛತ್ತೀಸ್‌ಗಢ'],['Goa','गोवा','ಗೋವಾ'],['Gujarat','गुजरात','ಗುಜರಾತ್'],['Haryana','हरियाणा','ಹರಿಯಾಣ'],['Himachal Pradesh','हिमाचल प्रदेश','ಹಿಮಾಚಲ ಪ್ರದೇಶ'],
['Jharkhand','झारखंड','ಜಾರ್ಖಂಡ್'],['Karnataka','कर्नाटक','ಕರ್ನಾಟಕ'],['Kerala','केरल','ಕೇರಳ'],['Madhya Pradesh','मध्य प्रदेश','ಮಧ್ಯ ಪ್ರದೇಶ'],['Maharashtra','महाराष्ट्र','ಮಹಾರಾಷ್ಟ್ರ'],
['Manipur','मणिपुर','ಮಣಿಪುರ'],['Meghalaya','मेघालय','ಮೇಘಾಲಯ'],['Mizoram','मिज़ोरम','ಮಿಜೋರಾಂ'],['Nagaland','नागालैंड','ನಾಗಾಲ್ಯಾಂಡ್'],['Odisha','ओडिशा','ಒಡಿಶಾ'],
['Punjab','पंजाब','ಪಂಜಾಬ್'],['Rajasthan','राजस्थान','ರಾಜಸ್ಥಾನ'],['Sikkim','सिक्किम','ಸಿಕ್ಕಿಂ'],['Tamil Nadu','तमिलनाडु','ತಮಿಳುನಾಡು'],['Telangana','तेलंगाना','ತೆಲಂಗಾಣ'],
['Tripura','त्रिपुरा','ತ್ರಿಪುರಾ'],['Uttar Pradesh','उत्तर प्रदेश','ಉತ್ತರ ಪ್ರದೇಶ'],['Uttarakhand','उत्तराखंड','ಉತ್ತರಾಖಂಡ'],['West Bengal','पश्चिम बंगाल','ಪಶ್ಚಿಮ ಬಂಗಾಳ'],
['Andaman and Nicobar Islands','अंडमान और निकोबार द्वीपसमूह','ಅಂಡಮಾನ್ ಮತ್ತು ನಿಕೋಬಾರ್ ದ್ವೀಪಗಳು'],['Chandigarh','चंडीगढ़','ಚಂಡೀಗಢ'],
['Dadra and Nagar Haveli and Daman and Diu','दादरा और नगर हवेली और दमन और दीव','ದಾದ್ರಾ ಮತ್ತು ನಗರ್ ಹವೇಲಿ ಮತ್ತು ದಮನ್ ಮತ್ತು ದಿಯು'],['Delhi','दिल्ली','ದೆಹಲಿ'],
['Jammu and Kashmir','जम्मू और कश्मीर','ಜಮ್ಮು ಮತ್ತು ಕಾಶ್ಮೀರ'],['Ladakh','लद्दाख','ಲಡಾಖ್'],['Lakshadweep','लक्षद्वीप','ಲಕ್ಷದ್ವೀಪ'],['Puducherry','पुदुचेरी','ಪುದುಚೇರಿ'],
/* tickets */
['Answered','उत्तर दिया गया','ಉತ್ತರಿಸಲಾಗಿದೆ'],['Closed','बंद','ಮುಚ್ಚಲಾಗಿದೆ'],
['Ask the laboratory a question or report a problem. The laboratory answers here; you are notified of every answer.','प्रयोगशाला से प्रश्न पूछें या कोई समस्या बताएँ। प्रयोगशाला यहीं उत्तर देती है; हर उत्तर की सूचना आपको मिलती है।','ಪ್ರಯೋಗಾಲಯಕ್ಕೆ ಪ್ರಶ್ನೆ ಕೇಳಿ ಅಥವಾ ಸಮಸ್ಯೆಯನ್ನು ವರದಿ ಮಾಡಿ. ಪ್ರಯೋಗಾಲಯವು ಇಲ್ಲಿಯೇ ಉತ್ತರಿಸುತ್ತದೆ; ಪ್ರತಿ ಉತ್ತರದ ಬಗ್ಗೆ ನಿಮಗೆ ಸೂಚನೆ ನೀಡಲಾಗುತ್ತದೆ.'],
['Ticket {id}','टिकट {id}','ಟಿಕೆಟ್ {id}'],['1 message','1 संदेश','1 ಸಂದೇಶ'],['{n} messages','{n} संदेश','{n} ಸಂದೇಶಗಳು'],
['No tickets yet. Raise one if you have a question about a request, a job or a report.','अभी कोई टिकट नहीं। यदि किसी अनुरोध, कार्य या रिपोर्ट के बारे में आपका कोई प्रश्न है, तो टिकट दर्ज करें।','ಇನ್ನೂ ಯಾವುದೇ ಟಿಕೆಟ್‌ಗಳಿಲ್ಲ. ವಿನಂತಿ, ಕಾರ್ಯ ಅಥವಾ ವರದಿಯ ಬಗ್ಗೆ ಪ್ರಶ್ನೆಯಿದ್ದರೆ ಟಿಕೆಟ್ ಸಲ್ಲಿಸಿ.'],
['Test request','परीक्षण अनुरोध','ಪರೀಕ್ಷಾ ವಿನಂತಿ'],['Test report','परीक्षण रिपोर्ट','ಪರೀಕ್ಷಾ ವರದಿ'],['Partial report or approved values','आंशिक रिपोर्ट या स्वीकृत मान','ಭಾಗಶಃ ವರದಿ ಅಥವಾ ಅನುಮೋದಿತ ಮೌಲ್ಯಗಳು'],
['Sample handling or despatch','नमूना प्रबंधन या प्रेषण','ಮಾದರಿ ನಿರ್ವಹಣೆ ಅಥವಾ ರವಾನೆ'],['Account or sign-in','खाता या साइन-इन','ಖಾತೆ ಅಥವಾ ಸೈನ್-ಇನ್'],['Other','अन्य','ಇತರೆ'],
["It goes to the laboratory's administrators. Describe the question or problem; mention the request or report it concerns.",'यह प्रयोगशाला के व्यवस्थापकों को जाता है। प्रश्न या समस्या का वर्णन करें; संबंधित अनुरोध या रिपोर्ट का उल्लेख करें।','ಇದು ಪ್ರಯೋಗಾಲಯದ ನಿರ್ವಾಹಕರಿಗೆ ಹೋಗುತ್ತದೆ. ಪ್ರಶ್ನೆ ಅಥವಾ ಸಮಸ್ಯೆಯನ್ನು ವಿವರಿಸಿ; ಸಂಬಂಧಿತ ವಿನಂತಿ ಅಥವಾ ವರದಿಯನ್ನು ಉಲ್ಲೇಖಿಸಿ.'],
['What is it about?','यह किस बारे में है?','ಇದು ಯಾವುದರ ಬಗ್ಗೆ?'],['Job (optional)','कार्य (वैकल्पिक)','ಕಾರ್ಯ (ಐಚ್ಛಿಕ)'],['Not about one job','किसी एक कार्य के बारे में नहीं','ಯಾವುದೇ ಒಂದು ಕಾರ್ಯದ ಬಗ್ಗೆ ಅಲ್ಲ'],
['Subject','विषय','ವಿಷಯ'],['In a few words','कुछ शब्दों में','ಕೆಲವು ಪದಗಳಲ್ಲಿ'],['Message','संदेश','ಸಂದೇಶ'],['Send to the laboratory','प्रयोगशाला को भेजें','ಪ್ರಯೋಗಾಲಯಕ್ಕೆ ಕಳುಹಿಸಿ'],
['Ticket sent to the laboratory','टिकट प्रयोगशाला को भेजा गया','ಟಿಕೆಟ್ ಅನ್ನು ಪ್ರಯೋಗಾಲಯಕ್ಕೆ ಕಳುಹಿಸಲಾಗಿದೆ'],['job','कार्य','ಕಾರ್ಯ'],['raised {at}','दर्ज {at}','ಸಲ್ಲಿಸಿದ್ದು {at}'],
['CPRI Short Circuit Laboratory','CPRI शॉर्ट सर्किट प्रयोगशाला','CPRI ಶಾರ್ಟ್ ಸರ್ಕ್ಯೂಟ್ ಪ್ರಯೋಗಾಲಯ'],
['Reply (re-opens the ticket)','उत्तर दें (टिकट फिर से खुलेगा)','ಉತ್ತರಿಸಿ (ಟಿಕೆಟ್ ಮತ್ತೆ ತೆರೆಯುತ್ತದೆ)'],['Reply','उत्तर','ಉತ್ತರ'],['Close the ticket','टिकट बंद करें','ಟಿಕೆಟ್ ಮುಚ್ಚಿ'],
['Send reply','उत्तर भेजें','ಉತ್ತರ ಕಳುಹಿಸಿ'],['Reply sent','उत्तर भेजा गया','ಉತ್ತರ ಕಳುಹಿಸಲಾಗಿದೆ'],['Ticket closed','टिकट बंद किया गया','ಟಿಕೆಟ್ ಮುಚ್ಚಲಾಗಿದೆ'],
['Choose what the ticket is about','चुनें कि टिकट किस बारे में है','ಟಿಕೆಟ್ ಯಾವುದರ ಬಗ್ಗೆ ಎಂದು ಆರಿಸಿ'],["That job is not one of your organisation's",'वह कार्य आपके संगठन का नहीं है','ಆ ಕಾರ್ಯವು ನಿಮ್ಮ ಸಂಸ್ಥೆಗೆ ಸೇರಿಲ್ಲ'],
/* assistant */
['Aletheia assistant','Aletheia सहायक','Aletheia ಸಹಾಯಕ'],['Your jobs, requests and reports','आपके कार्य, अनुरोध और रिपोर्ट','ನಿಮ್ಮ ಕಾರ್ಯಗಳು, ವಿನಂತಿಗಳು ಮತ್ತು ವರದಿಗಳು'],
['Ask, or type a series or sample number','पूछें, या सीरीज़ या नमूना संख्या लिखें','ಕೇಳಿ, ಅಥವಾ ಸರಣಿ ಅಥವಾ ಮಾದರಿ ಸಂಖ್ಯೆಯನ್ನು ಟೈಪ್ ಮಾಡಿ'],['Send','भेजें','ಕಳುಹಿಸಿ'],
['Open the assistant','सहायक खोलें','ಸಹಾಯಕವನ್ನು ತೆರೆಯಿರಿ'],['Close the assistant','सहायक बंद करें','ಸಹಾಯಕವನ್ನು ಮುಚ್ಚಿ'],['Message the assistant','सहायक को संदेश भेजें','ಸಹಾಯಕಕ್ಕೆ ಸಂದೇಶ ಕಳುಹಿಸಿ'],
['My jobs','मेरे कार्य','ನನ್ನ ಕಾರ್ಯಗಳು'],['Released reports','जारी रिपोर्ट','ಬಿಡುಗಡೆಯಾದ ವರದಿಗಳು'],['How it works','यह कैसे काम करता है','ಇದು ಹೇಗೆ ಕೆಲಸ ಮಾಡುತ್ತದೆ'],
['None of your jobs match <b>{t}</b>.','आपका कोई भी कार्य <b>{t}</b> से मेल नहीं खाता।','ನಿಮ್ಮ ಯಾವುದೇ ಕಾರ್ಯವು <b>{t}</b> ಗೆ ಹೊಂದಿಕೆಯಾಗುತ್ತಿಲ್ಲ.'],
['No report has been released yet. You are notified when one is.','अभी तक कोई रिपोर्ट जारी नहीं हुई है। जारी होने पर आपको सूचित किया जाएगा।','ಇನ್ನೂ ಯಾವುದೇ ವರದಿ ಬಿಡುಗಡೆಯಾಗಿಲ್ಲ. ಬಿಡುಗಡೆಯಾದಾಗ ನಿಮಗೆ ತಿಳಿಸಲಾಗುತ್ತದೆ.'],
['You have no jobs yet. A job starts when the laboratory accepts your test request.','अभी आपका कोई कार्य नहीं है। प्रयोगशाला द्वारा आपका परीक्षण अनुरोध स्वीकार किए जाने पर कार्य शुरू होता है।','ನಿಮಗೆ ಇನ್ನೂ ಯಾವುದೇ ಕಾರ್ಯಗಳಿಲ್ಲ. ಪ್ರಯೋಗಾಲಯವು ನಿಮ್ಮ ಪರೀಕ್ಷಾ ವಿನಂತಿಯನ್ನು ಅಂಗೀಕರಿಸಿದಾಗ ಕಾರ್ಯ ಪ್ರಾರಂಭವಾಗುತ್ತದೆ.'],
['1 released report (open the job to download it):','1 जारी रिपोर्ट (डाउनलोड करने के लिए कार्य खोलें):','1 ಬಿಡುಗಡೆಯಾದ ವರದಿ (ಡೌನ್‌ಲೋಡ್ ಮಾಡಲು ಕಾರ್ಯವನ್ನು ತೆರೆಯಿರಿ):'],
['{n} released reports (open a job to download it):','{n} जारी रिपोर्ट (डाउनलोड करने के लिए कार्य खोलें):','{n} ಬಿಡುಗಡೆಯಾದ ವರದಿಗಳು (ಡೌನ್‌ಲೋಡ್ ಮಾಡಲು ಕಾರ್ಯವನ್ನು ತೆರೆಯಿರಿ):'],
['1 job matches <b>{t}</b>:','1 कार्य <b>{t}</b> से मेल खाता है:','1 ಕಾರ್ಯ <b>{t}</b> ಗೆ ಹೊಂದಿಕೆಯಾಗುತ್ತದೆ:'],['{n} jobs match <b>{t}</b>:','{n} कार्य <b>{t}</b> से मेल खाते हैं:','{n} ಕಾರ್ಯಗಳು <b>{t}</b> ಗೆ ಹೊಂದಿಕೆಯಾಗುತ್ತವೆ:'],
['Your job:','आपका कार्य:','ನಿಮ್ಮ ಕಾರ್ಯ:'],['Your {n} jobs, most recent first:','आपके {n} कार्य, सबसे हाल वाला पहले:','ನಿಮ್ಮ {n} ಕಾರ್ಯಗಳು, ಇತ್ತೀಚಿನದು ಮೊದಲು:'],
['Hello! What would you like to do?','नमस्ते! आप क्या करना चाहेंगे?','ನಮಸ್ಕಾರ! ನೀವು ಏನು ಮಾಡಲು ಬಯಸುತ್ತೀರಿ?'],
['Opening a new test request.','नया परीक्षण अनुरोध खोला जा रहा है।','ಹೊಸ ಪರೀಕ್ಷಾ ವಿನಂತಿಯನ್ನು ತೆರೆಯಲಾಗುತ್ತಿದೆ.'],
['Opening a new ticket to the laboratory.','प्रयोगशाला के लिए नया टिकट खोला जा रहा है।','ಪ್ರಯೋಗಾಲಯಕ್ಕೆ ಹೊಸ ಟಿಕೆಟ್ ತೆರೆಯಲಾಗುತ್ತಿದೆ.'],
["Sorry, I didn't understand that. Try one of these, or type <i>help</i>.",'क्षमा करें, मैं यह समझ नहीं पाया। इनमें से कोई एक आज़माएँ, या <i>मदद</i> लिखें।','ಕ್ಷಮಿಸಿ, ನನಗೆ ಅದು ಅರ್ಥವಾಗಲಿಲ್ಲ. ಇವುಗಳಲ್ಲಿ ಒಂದನ್ನು ಪ್ರಯತ್ನಿಸಿ, ಅಥವಾ <i>ಸಹಾಯ</i> ಎಂದು ಟೈಪ್ ಮಾಡಿ.'],
["Hello, I'm the Aletheia assistant. I can show your jobs and released reports, open a new test request, or raise a ticket to the laboratory.",'नमस्ते, मैं Aletheia सहायक हूँ। मैं आपके कार्य और जारी रिपोर्ट दिखा सकता हूँ, नया परीक्षण अनुरोध खोल सकता हूँ, या प्रयोगशाला के लिए टिकट दर्ज कर सकता हूँ।','ನಮಸ್ಕಾರ, ನಾನು Aletheia ಸಹಾಯಕ. ನಿಮ್ಮ ಕಾರ್ಯಗಳು ಮತ್ತು ಬಿಡುಗಡೆಯಾದ ವರದಿಗಳನ್ನು ತೋರಿಸಬಲ್ಲೆ, ಹೊಸ ಪರೀಕ್ಷಾ ವಿನಂತಿಯನ್ನು ತೆರೆಯಬಲ್ಲೆ, ಅಥವಾ ಪ್ರಯೋಗಾಲಯಕ್ಕೆ ಟಿಕೆಟ್ ಸಲ್ಲಿಸಬಲ್ಲೆ.'],
['Something went wrong:','कुछ गड़बड़ हो गई:','ಏನೋ ತಪ್ಪಾಗಿದೆ:'],
];
const L10N={hi:{},kn:{}};I18N.forEach(([en,hi,kn])=>{L10N.hi[en]=hi;L10N.kn[en]=kn});

/* translate only for a signed-in customer who chose Hindi or Kannada */
const useLang=()=>LANG!='en'&&typeof isCust=='function'&&isCust();
const curLang=()=>useLang()?LANG:'en';
function T(s,v){let r=useLang()&&L10N[LANG][s]||s;if(v)r=r.replace(/\{(\w+)\}/g,(m,k)=>v[k]!=null?v[k]:m);return r}
/* dates in the customer's language */
const LOC=()=>({hi:'hi-IN',kn:'kn-IN'})[curLang()]||'en-GB';

/* messages written by the server: [pattern, Hindi, Kannada]; a function gets the match and returns the text */
const tq=s=>T(s);
const TAIL=[
 [/^required( \(or mark it not applicable, with a reason\))?(?: - '(.*)' is not accepted)?$/,
  m=>(m[1]?'आवश्यक (या कारण सहित "लागू नहीं" चिह्नित करें)':'आवश्यक')+(m[2]!=null?` - '${m[2]}' स्वीकार्य नहीं है`:''),
  m=>(m[1]?'ಅಗತ್ಯವಿದೆ (ಅಥವಾ ಕಾರಣದೊಂದಿಗೆ "ಅನ್ವಯಿಸುವುದಿಲ್ಲ" ಎಂದು ಗುರುತಿಸಿ)':'ಅಗತ್ಯವಿದೆ')+(m[2]!=null?` - '${m[2]}' ಸ್ವೀಕಾರಾರ್ಹವಲ್ಲ`:'')],
 [/^cannot be marked not applicable$/,()=>'"लागू नहीं" के रूप में चिह्नित नहीं किया जा सकता',()=>'"ಅನ್ವಯಿಸುವುದಿಲ್ಲ" ಎಂದು ಗುರುತಿಸಲಾಗುವುದಿಲ್ಲ'],
 [/^give the reason it does not apply$/,()=>'लागू न होने का कारण बताएँ',()=>'ಅನ್ವಯಿಸದಿರುವ ಕಾರಣವನ್ನು ನೀಡಿ'],
 [/^must be 6 digits, not starting with 0 \(got '(.*)'\)$/,m=>`6 अंकों का होना चाहिए, 0 से शुरू नहीं (दर्ज: '${m[1]}')`,m=>`6 ಅಂಕಿಗಳಾಗಿರಬೇಕು, 0 ಯಿಂದ ಪ್ರಾರಂಭವಾಗಬಾರದು (ನಮೂದಿಸಿದ್ದು: '${m[1]}')`],
 [/^10-12 digits, optionally with \+country code \(got '(.*)'\)$/,m=>`10-12 अंक, चाहें तो +देश कोड सहित (दर्ज: '${m[1]}')`,m=>`10-12 ಅಂಕಿಗಳು, ಬೇಕಿದ್ದರೆ +ದೇಶದ ಕೋಡ್‌ನೊಂದಿಗೆ (ನಮೂದಿಸಿದ್ದು: '${m[1]}')`],
 [/^not a valid address \(got '(.*)'\)$/,m=>`मान्य पता नहीं है (दर्ज: '${m[1]}')`,m=>`ಮಾನ್ಯ ವಿಳಾಸವಲ್ಲ (ನಮೂದಿಸಿದ್ದು: '${m[1]}')`],
 [/^'(.*)' is not an Indian state or union territory$/,m=>`'${m[1]}' भारत का राज्य या केंद्र शासित प्रदेश नहीं है`,m=>`'${m[1]}' ಭಾರತದ ರಾಜ್ಯ ಅಥವಾ ಕೇಂದ್ರಾಡಳಿತ ಪ್ರದೇಶವಲ್ಲ`],
 [/^a number with its unit, like '250 kVA' \(got '(.*)'\)$/,m=>`इकाई सहित संख्या, जैसे '250 kVA' (दर्ज: '${m[1]}')`,m=>`ಘಟಕದೊಂದಿಗೆ ಸಂಖ್ಯೆ, ಉದಾ. '250 kVA' (ನಮೂದಿಸಿದ್ದು: '${m[1]}')`],
 [/^a whole number, 1 or more \(got '(.*)'\)$/,m=>`1 या उससे अधिक पूर्ण संख्या (दर्ज: '${m[1]}')`,m=>`1 ಅಥವಾ ಹೆಚ್ಚಿನ ಪೂರ್ಣ ಸಂಖ್ಯೆ (ನಮೂದಿಸಿದ್ದು: '${m[1]}')`],
 [/^answer yes or no$/,()=>'हाँ या नहीं में उत्तर दें',()=>'ಹೌದು ಅಥವಾ ಇಲ್ಲ ಎಂದು ಉತ್ತರಿಸಿ'],
 [/^choose one of the options$/,()=>'विकल्पों में से एक चुनें',()=>'ಆಯ್ಕೆಗಳಲ್ಲಿ ಒಂದನ್ನು ಆರಿಸಿ'],
 [/^answer Yes to exactly one of \(a\) and \(b\)$/,()=>'(a) और (b) में से केवल एक का उत्तर "हाँ" दें',()=>'(a) ಮತ್ತು (b) ಯಲ್ಲಿ ಕೇವಲ ಒಂದಕ್ಕೆ "ಹೌದು" ಎಂದು ಉತ್ತರಿಸಿ'],
 [/^tick at least one test$/,()=>'कम से कम एक परीक्षण चुनें',()=>'ಕನಿಷ್ಠ ಒಂದು ಪರೀಕ್ಷೆಯನ್ನು ಆಯ್ಕೆಮಾಡಿ'],
 [/^say in a few words what it is about$/,()=>'कुछ शब्दों में बताएँ कि यह किस बारे में है',()=>'ಇದು ಯಾವುದರ ಬಗ್ಗೆ ಎಂದು ಕೆಲವು ಪದಗಳಲ್ಲಿ ತಿಳಿಸಿ'],
 [/^describe the question or problem \(at least 10 characters\)$/,()=>'प्रश्न या समस्या का वर्णन करें (कम से कम 10 अक्षर)',()=>'ಪ್ರಶ್ನೆ ಅಥವಾ ಸಮಸ್ಯೆಯನ್ನು ವಿವರಿಸಿ (ಕನಿಷ್ಠ 10 ಅಕ್ಷರಗಳು)']];
const WHOLE=[
 [/^Declaration not accepted: (.*)$/,m=>'घोषणा स्वीकार नहीं की गई: '+tq(m[1]),m=>'ಘೋಷಣೆಯನ್ನು ಒಪ್ಪಿಕೊಂಡಿಲ್ಲ: '+tq(m[1])],
 [/^PIN code (\d+): this prefix is not a known postal circle$/,m=>`पिन कोड ${m[1]}: यह उपसर्ग किसी ज्ञात डाक सर्कल का नहीं है`,m=>`ಪಿನ್ ಕೋಡ್ ${m[1]}: ಈ ಪೂರ್ವಪ್ರತ್ಯಯ ಯಾವುದೇ ತಿಳಿದಿರುವ ಅಂಚೆ ವೃತ್ತಕ್ಕೆ ಸೇರಿಲ್ಲ`],
 [/^PIN code (\d+) belongs to (.+), but the state is (.+)$/,m=>`पिन कोड ${m[1]} ${m[2].split(' / ').map(tq).join(' / ')} का है, लेकिन राज्य ${tq(m[3])} है`,m=>`ಪಿನ್ ಕೋಡ್ ${m[1]} ${m[2].split(' / ').map(tq).join(' / ')} ಗೆ ಸೇರಿದೆ, ಆದರೆ ರಾಜ್ಯ ${tq(m[3])} ಆಗಿದೆ`],
 [/^Your test request (\d+) was returned for correction: ([\s\S]*)$/,m=>`आपका परीक्षण अनुरोध ${m[1]} सुधार के लिए लौटाया गया: ${m[2]}`,m=>`ನಿಮ್ಮ ಪರೀಕ್ಷಾ ವಿನಂತಿ ${m[1]} ಅನ್ನು ತಿದ್ದುಪಡಿಗಾಗಿ ಹಿಂತಿರುಗಿಸಲಾಗಿದೆ: ${m[2]}`],
 [/^Test report (.+?) is ready(?: \(corrected version (\d+)\))?\. View and download it here\.$/,
  m=>`परीक्षण रिपोर्ट ${m[1]} तैयार है${m[2]?` (सुधारा गया संस्करण ${m[2]})`:''}। इसे यहाँ देखें और डाउनलोड करें।`,
  m=>`ಪರೀಕ್ಷಾ ವರದಿ ${m[1]} ಸಿದ್ಧವಾಗಿದೆ${m[2]?` (ತಿದ್ದುಪಡಿ ಆವೃತ್ತಿ ${m[2]})`:''}. ಇಲ್ಲಿ ನೋಡಿ ಮತ್ತು ಡೌನ್‌ಲೋಡ್ ಮಾಡಿ.`],
 [/^The laboratory answered your ticket (\d+): ([\s\S]*)$/,m=>`प्रयोगशाला ने आपके टिकट ${m[1]} का उत्तर दिया: ${m[2]}`,m=>`ಪ್ರಯೋಗಾಲಯವು ನಿಮ್ಮ ಟಿಕೆಟ್ ${m[1]} ಗೆ ಉತ್ತರಿಸಿದೆ: ${m[2]}`],
 [/^Your ticket (\d+) was closed: ([\s\S]*)$/,m=>`आपका टिकट ${m[1]} बंद कर दिया गया: ${m[2]}`,m=>`ನಿಮ್ಮ ಟಿಕೆಟ್ ${m[1]} ಅನ್ನು ಮುಚ್ಚಲಾಗಿದೆ: ${m[2]}`]];
function TF(msg){msg=String(msg??'');if(!useLang())return msg;const i=LANG=='hi'?1:2;
 if(L10N[LANG][msg])return L10N[LANG][msg];
 for(const p of WHOLE){const m=msg.match(p[0]);if(m)return p[i](m)}
 const c=msg.match(/^(.+?): ([\s\S]+)$/);   /* "<field label>: <problem>" */
 if(c&&L10N[LANG][c[1]])for(const p of TAIL){const m=c[2].match(p[0]);if(m)return T(c[1])+': '+p[i](m)}
 return msg}

/* the switch in the customer's top bar */
function langSwitch(){if(!isCust())return'';return `<label class="lsw" title="${T('Language')}"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.7 3.8 5.7 3.8 9s-1.3 6.3-3.8 9c-2.5-2.7-3.8-5.7-3.8-9S9.5 5.7 12 3z"/></svg><select aria-label="${T('Language')}" onchange="setLang(this.value)">${LANGS.map(([k,l])=>`<option value="${k}" lang="${k}"${k==LANG?' selected':''}>${l}</option>`).join('')}</select></label>`}
function applyLang(){document.documentElement.lang=curLang()}
function setLang(l){LANG=LANGS.some(x=>x[0]==l)?l:'en';try{localStorage.setItem('aletheia_lang',LANG)}catch(e){}applyLang();
 const cb=document.getElementById('cb');if(cb)cb.remove();if(typeof assistantMount=='function')assistantMount();route()}
