% Scenario SAA Simulator
% Version 0.1
% Author Nicolas Buerkler
clear all, clc, close all

%% Simulation time in months
T=60; times = linspace(0, 1, T);

%% Select scenario (1 to 4)
s=3; % 1: Depression, 2: Hyperinflation, 3: Stagflation, 4: Deferral

%% MRS start
MRS_start=rand(1,25); % take current real MRS
MRS_start=MRS_start/sum(MRS_start);

%% Create binominal table
Binom=[1.5 2 4.9 6 8.9 13 13.7 13.7 12 8.9 6 4.9 2 1.5]/100;
Binom_Bust=[14.4 21.9 13.7 13.7 12 8.9 6 4.9 2 1.5]/100;
Binom_Boom=fliplr(Binom_Bust);

%% Modelling target MRS, defaults, valuations & Inflation
switch s
    case 1
        % Scenario Depression
        M1(:)=[0 0 0.25 0.75]; % Boom, Recovery, Contraction, Bust

        startVal=0.02; endVal=-0.04; midpoint=0.5; steepness = 20; range = startVal - endVal;
        inflation = fliplr(endVal + range ./ (1 + exp(-steepness * (times - midpoint))));

        startVal = 1; endVal = 0.6; inflectionPoint = 0.5; steepness = 2.5; totalChange = startVal - endVal;
        defaults = zeros(size(times));
		
        for i = 1:length(times)
            t = times(i);
            if t <= inflectionPoint
                defaults(i) = startVal - totalChange * (t/inflectionPoint)^(1/steepness) * 0.3;
            else
                t_norm = (t - inflectionPoint) / (1 - inflectionPoint);
                valueAtInflection = startVal - totalChange * 0.3;
                remainingChange = valueAtInflection - endVal;
                defaults(i) = valueAtInflection - remainingChange * t_norm^steepness;
            end
        end
        valuations=[linspace(1,0.5,30) 0.5*ones(1,30)];

    case 2
        % Scenario Hyperinfation
        M1(:)=[1 0 0 0]; % Boom, Recovery, Contraction, Bust

        startVal=0.2; endVal =1; power=4;
        inflation = startVal * exp(log(endVal / startVal) * times.^power);

        defaults = ones(size(times));

        valuations=ones(1,T);


    case 3
        % Scenario Stagflation
        M1(:)=[0.5 0.25 0.25 0]; % Boom, Recovery, Contraction, Bust

        startVal = 0.02; endVal = 0.1; midpoint = 0.3; steepness = 15; range = endVal - startVal;
        inflation = startVal + range ./ (1 + exp(-steepness * (times - midpoint)));

        startVal = 1; endVal = 0.8; inflectionPoint = 0.5; steepness = 2.5; totalChange = startVal - endVal;
        defaults = zeros(size(times));
		
        for i = 1:length(times)
            t = times(i);
            if t <= inflectionPoint
                defaults(i) = startVal - totalChange * (t/inflectionPoint)^(1/steepness) * 0.3;
            else
                t_norm = (t - inflectionPoint) / (1 - inflectionPoint);
                valueAtInflection = startVal - totalChange * 0.3;
                remainingChange = valueAtInflection - endVal;
                defaults(i) = valueAtInflection - remainingChange * t_norm^steepness;
            end
        end
        valuations=[linspace(1,0.7,20) 0.7*ones(1,40)];


    case 4
        % Scenario Deferral
        M1(:)=[0.5 0 0 0.5]; % Boom, Recovery, Contraction, Bust

        startVal = 0.02; peakVal = 0.06; peakPosition = 0.5; range = peakVal - startVal;
        sigma1 = peakPosition / 2.5; sigma2 = (1-peakPosition) / 2.5; inflation = zeros(size(times));
        for i = 1:length(times)
            t = times(i);
            if t <= peakPosition
                % Rising part (scaled Gaussian)
                inflation(i) = startVal + range * exp(-0.5 * ((t - peakPosition) / sigma1)^2);
            else
                % Falling part (scaled Gaussian)
                inflation(i) = startVal + range * exp(-0.5 * ((t - peakPosition) / sigma2)^2);
            end
        end
        startVal = 1; endVal = 0.9; inflectionPoint = 0.5; steepness = 2.5; totalChange = startVal - endVal;
        defaults = zeros(size(times));
		
        for i = 1:length(times)
            t = times(i);
            if t <= inflectionPoint
                defaults(i) = startVal - totalChange * (t/inflectionPoint)^(1/steepness) * 0.3;
            else
                t_norm = (t - inflectionPoint) / (1 - inflectionPoint);
                valueAtInflection = startVal - totalChange * 0.3;
                remainingChange = valueAtInflection - endVal;
                defaults(i) = valueAtInflection - remainingChange * t_norm^steepness;
            end
        end
        valuations=[linspace(1,0.8,50) 0.8*ones(1,10)];

end
M1=fliplr(M1);

%% creating indivudal Market Risk Signal
MRS = zeros(T, 25);
MRS(T,:) = [M1(1)*Binom_Bust, zeros(1,15)]+[zeros(1,2), M1(2)*Binom, zeros(1,9)]+[zeros(1,9), M1(3)*Binom, zeros(1,2)]+[zeros(1,15), M1(4)*Binom_Boom];

% Perform the gradual transformation from Starting MRS to targe MRS 
for i = 1:T
    % Calculate difference between current and target
    difference = MRS(T,:) - MRS_start;

    % Move a fraction toward the target each step
    step = difference / (T - i + 1);
    MRS_start = MRS_start + step;
    MRS_start=MRS_start/sum(MRS_start);

    % Store current state
    MRS(i, :) = MRS_start;
end
%surf(MRS)


%% Transform Return profiles

for i=1:size(defaults,2)
    % Cash: no transformation

    % Fixed Income IG * default
    ret_FI_IG=[-12,-10,-8,-7,-5,-3,-2,-1,0,1,1,1,2,3,6,8,10,11,13,14,15,16,16,16,16];
    ret_FI_IG_scen(i,:)=max(-100,defaults(i).^sign(ret_FI_IG).*ret_FI_IG);


    % Fixed Income HY * default * 2
    ret_FI_HI=[-20,-15,-8,-7,-5,-3,-2,-1,0,1,1,1,2,3,6,8,10,11,13,14,15,16,16,16,16];
    ret_FI_HI_scen(i,:)=max(-100,(2*defaults(i)).^sign(ret_FI_HI).*ret_FI_HI);


    % Equities
    % US * valuation * 2
    ret_EQ_US=[-20,-15,-8,-7,-5,-3,-2,-1,0,1,1,1,2,3,6,8,10,11,13,14,15,16,16,16,16];
    ret_EQ_US_scen(i,:)=max(-100,(2*valuations(i)).^sign(ret_EQ_US).*ret_EQ_US);
    % EU * valuation * 2
    % China * valuation    
    ret_EQ_CN=[-20,-15,-8,-7,-5,-3,-2,-1,0,1,1,1,2,3,6,8,10,11,13,14,15,16,16,16,16];
    ret_EQ_CN_scen(i,:)=max(-100,(valuations(i)).^sign(ret_EQ_CN).*ret_EQ_CN);
    % SEA * valuation
    % Japan * valuation * 2


    % Commodities * valuation

    % Market Neutral Hedge Funds * valuation

    % Real Estate  * valuation * default
    ret_RE=[-20,-15,-8,-7,-5,-3,-2,-1,0,1,1,1,2,3,6,8,10,11,13,14,15,16,16,16,16];
    ret_RE_scen(i,:)=max(-100,defaults(i).^sign(ret_RE).*valuations(i).^sign(ret_RE).*ret_RE);

    % Precious Metals / Gold

end
 

%% Portfolio Optimization