'use strict';
// Presentation-only location catalog. Add countries/cities here without changing
// the analysis endpoint. Course and Student remain future domain entities.
const LOCATION_OPTIONS = {
  Australia: {
    cities: {
      Sydney: {universities: ['UTS', 'University of Sydney', 'UNSW', 'Macquarie University', 'Western Sydney University']},
      Melbourne: {universities: ['University of Melbourne', 'Monash University', 'RMIT University', 'Deakin University', 'La Trobe University']},
      Brisbane: {universities: ['University of Queensland', 'Queensland University of Technology', 'Griffith University']},
      Other: {universities: []}
    }
  },
  Other: {cities: {Other: {universities: []}}}
};
// Keep city scenery separate from the mascot. A future United Kingdom / London
// entry can point to a Big Ben image. Unconfigured cities use a neutral fallback.
const CITY_VISUALS = {
  Australia: {
    Sydney: {
      image: '/static/images/sydney-hero-original.png',
      landmark: 'Sydney Opera House',
      altZh: '蓝天与阳光下的悉尼歌剧院，用户提供的高清城市主视觉',
      altEn: 'Sydney Opera House under a blue sky, supplied city artwork',
      position: '65% 52%'
    }
  }
};
