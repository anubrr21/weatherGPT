export interface Language {
  code: string
  speech: string
  native: string
  english: string
}

export const LANGUAGES: Language[] = [
  { code: 'en', speech: 'en-IN', native: 'English', english: 'English' },
  { code: 'hi', speech: 'hi-IN', native: 'हिन्दी', english: 'Hindi' },
  { code: 'bn', speech: 'bn-IN', native: 'বাংলা', english: 'Bengali' },
  { code: 'te', speech: 'te-IN', native: 'తెలుగు', english: 'Telugu' },
  { code: 'ta', speech: 'ta-IN', native: 'தமிழ்', english: 'Tamil' },
  { code: 'mr', speech: 'mr-IN', native: 'मराठी', english: 'Marathi' },
  { code: 'gu', speech: 'gu-IN', native: 'ગુજરાતી', english: 'Gujarati' },
  { code: 'kn', speech: 'kn-IN', native: 'ಕನ್ನಡ', english: 'Kannada' },
  { code: 'ml', speech: 'ml-IN', native: 'മലയാളം', english: 'Malayalam' },
  { code: 'or', speech: 'or-IN', native: 'ଓଡ଼ିଆ', english: 'Odia' },
  { code: 'pa', speech: 'pa-IN', native: 'ਪੰਜਾਬੀ', english: 'Punjabi' },
  { code: 'as', speech: 'as-IN', native: 'অসমীয়া', english: 'Assamese' },
  { code: 'ur', speech: 'ur-IN', native: 'اردو', english: 'Urdu' },
]

export const languageByCode = (code: string) => LANGUAGES.find((l) => l.code === code) ?? LANGUAGES[0]

export const PROMPTS: Record<string, { persona: string; text: string }[]> = {
  en: [
    { persona: 'Farmer', text: 'Is it safe to spray pesticide on my paddy field tomorrow morning?' },
    { persona: 'Fisher', text: 'Can boats go out from Visakhapatnam today? How rough is the sea?' },
    { persona: 'Aviation', text: 'Give me a weather briefing for Delhi airport VIDP' },
    { persona: 'Safety', text: 'Are there any IMD warnings for my area right now?' },
    { persona: 'Climate', text: 'Has this place become hotter over the last 30 years?' },
    { persona: 'Confidence', text: 'How much do GFS, ECMWF and ICON disagree this week?' },
  ],
  hi: [
    { persona: 'किसान', text: 'क्या कल सुबह धान में कीटनाशक छिड़कना ठीक रहेगा?' },
    { persona: 'चेतावनी', text: 'क्या मेरे इलाके के लिए IMD की कोई चेतावनी है?' },
    { persona: 'मौसम', text: 'अगले तीन दिन बारिश होगी क्या?' },
    { persona: 'हवा', text: 'दिल्ली में आज हवा कितनी प्रदूषित है?' },
  ],
}
